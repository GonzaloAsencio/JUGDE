"""EXPERIMENT (LLM-free, non-destructive): does prepending parent-rule lineage to
rulebook chunks rescue the (A) granularity misses?

Lever 2 of plan perf/retrieval-misses. The granularity misses (eval-015, eval-017)
fail because a sub-rule chunk (e.g. 383.4.e) carries only its coarse H3 section
header ("360. Abilities") and lost the semantic context of its parent rule
("383. Triggered Abilities"). This probe re-chunks the rulebook with a lineage
breadcrumb ("Rule 383: Triggered Abilities") prepended, embeds the FULL corpus
(all sources, so card chunks still compete for rank) IN MEMORY twice — baseline
vs lineage — and measures recall@5/@10/@15. The DB is never touched; only a
winner gets ported to ingest.py (Phase 2) and re-ingested (Phase 3).

Usage (from backend/):
    python -m scripts.lineage_offline_probe

Requires the processed corpus on disk (data/processed/*.md). Does NOT require
DATABASE_URL or GEMINI_API_KEY. Loads BAAI/bge-m3 and embeds ~1300 chunks
(baseline + lineage) — a few minutes, no network/LLM cost.
"""
import re
import sys

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from scripts.eval_judge import _parse_refs
from scripts.ingest import (
    SOURCES,
    _make_chunk,
    _split_into_sections,
    _strip_header_line,
    _RULE_LINE_START,
    _RULE_UNIT_SPLIT,
    _RULE_SPLIT,
    _approx_tokens,
    _detect_set,
    build_chunks,
    RULEBOOK_CHUNK_SIZE,
)
from scripts.retrieval_probe import _load_evaluable, recall_at_k
from app.rag.rules import extract_rule_codes

TOP_K = 15
_TARGET_MISSES = {"eval-015", "eval-017"}  # the (A) granularity misses

# A bare top-level rule line: "383. **Triggered Abilities** ..." (NNN. + space),
# NOT a sub-rule "383.3. ..." (NNN.<digit>).
_TOP_LEVEL = re.compile(r"^(\d{3})\.\s")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


# ---------------------------------------------------------------------------
# Lineage chunker (pure — unit-tested in tests/test_lineage_offline_probe.py)
# ---------------------------------------------------------------------------

def rule_title(unit: str) -> str | None:
    """First bold term of a top-level rule unit ('383. **Triggered Abilities**…'
    -> 'Triggered Abilities'). None if no bold term."""
    m = _BOLD.search(unit)
    return m.group(1).strip() if m else None


def _unit_breadcrumbs(units: list[str]) -> list[tuple[str, str] | None]:
    """For each unit, the inherited (base, title) of the top-level rule in force.

    Walking in order, a bare ``NNN.`` unit sets the current base + title; every
    following sub-rule unit inherits it until the next top-level rule appears.
    """
    out: list[tuple[str, str] | None] = []
    current: tuple[str, str] | None = None
    for u in units:
        m = _TOP_LEVEL.match(u)
        if m:
            title = rule_title(u)
            current = (m.group(1), title) if title else (m.group(1), "")
        out.append(current)
    return out


def _split_units(body: str, budget: int) -> list[str]:
    """Same unit split as ingest._chunk_rulebook_section: by rule, sub-dividing
    any over-budget single-line unit by inline rule boundaries."""
    raw = [u.strip() for u in _RULE_UNIT_SPLIT.split(body) if u.strip()]
    units: list[str] = []
    for u in raw:
        if _approx_tokens(u) > budget:
            units.extend(p.strip() for p in _RULE_SPLIT.split(u) if p.strip())
        else:
            units.append(u)
    return units


def chunk_rulebook_lineage(content: str, header: str, parent: str, source_document: str,
                           metadata: dict | None, budget: int = RULEBOOK_CHUNK_SIZE) -> list[dict]:
    """Lineage variant of ingest._chunk_rulebook_section: each chunk's header line
    is enriched with the parent rule breadcrumb ('Rule 383: Triggered Abilities')
    inherited from the most recent top-level rule, so a stranded sub-rule chunk
    embeds with its parent's context. Grouping/budget logic is identical."""
    body = _strip_header_line(content)
    units = _split_units(body, budget)
    crumbs = _unit_breadcrumbs(units)

    chunks: list[dict] = []
    current: list[str] = []
    current_crumb: tuple[str, str] | None = None

    def header_line(crumb):
        if crumb and crumb[0]:
            title = f": {crumb[1]}" if crumb[1] else ""
            return f"### {header} — Rule {crumb[0]}{title}"
        return f"### {header}"

    def render(units_, crumb):
        return header_line(crumb) + "\n" + "\n".join(units_)

    def flush():
        nonlocal current, current_crumb
        if current:
            chunks.append(_make_chunk(render(current, current_crumb), header, parent,
                                      "rulebook", source_document, metadata))
            current = []
            current_crumb = None

    for unit, crumb in zip(units, crumbs):
        if current and _approx_tokens(render(current + [unit], current_crumb)) > budget:
            flush()
        if not current:
            current_crumb = crumb  # breadcrumb anchored on the chunk's first unit
        current.append(unit)

    flush()
    return chunks


# ---------------------------------------------------------------------------
# Corpus builders (baseline vs lineage) — full corpus, all sources
# ---------------------------------------------------------------------------

def _build_lineage_chunks(source_path: str, source_type: str) -> list[dict]:
    """Like ingest.build_chunks but rulebook rule-sections use the lineage chunker."""
    from pathlib import Path
    path = Path(source_path)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    sections = _split_into_sections(text)
    stem = path.stem
    doc_set = _detect_set(stem)
    out: list[dict] = []
    for section in sections:
        content = section["content"]
        header = section["header"]
        parent = f"Level {section['level']} — {header}"
        section_set = _detect_set("cards", content) if stem == "cards" else doc_set
        body = _strip_header_line(content)
        if source_type == "rulebook" and body and _RULE_LINE_START.search(body):
            out.extend(chunk_rulebook_lineage(content, header, parent, stem,
                                              {"set": section_set}))
        else:
            # Non-rule sections: identical to baseline.
            from scripts.ingest import _chunk_section
            out.extend(_chunk_section(section, source_type, stem, {"set": section_set}))
    return out


def _all_chunks(builder) -> list[dict]:
    chunks: list[dict] = []
    for path, stype in SOURCES:
        chunks.extend(builder(path, stype))
    return chunks


# ---------------------------------------------------------------------------
# In-memory index + recall
# ---------------------------------------------------------------------------

def _embed_all(model, contents: list[str]) -> np.ndarray:
    return np.asarray(model.encode(contents, batch_size=32, normalize_embeddings=True,
                                   show_progress_bar=True))


def _rank_of_gold(refs, chunks, sims) -> int | None:
    order = np.argsort(-sims)  # descending cosine (normalized -> dot)
    for rank, idx in enumerate(order[:TOP_K], 1):
        c = chunks[idx]
        codes = extract_rule_codes(c["content"])
        for ref in refs:
            if ref.startswith("errata/"):
                if c["source_type"] == "errata":
                    return rank
            elif any(code == ref or code.startswith(ref + ".") or ref.startswith(code + ".")
                     for code in codes):
                return rank
    return None


def _measure(model, chunks, questions) -> dict:
    mat = _embed_all(model, [c["content"] for c in chunks])
    ranks: dict[str, int | None] = {}
    for q in questions:
        qv = np.asarray(model.encode(q["question"], normalize_embeddings=True))
        sims = mat @ qv
        ranks[q.get("id", "?")] = _rank_of_gold(_parse_refs(q["rule_reference"]), chunks, sims)
    return ranks


def _report(base_ranks, lin_ranks, questions):
    ids = [q.get("id", "?") for q in questions]
    base = [base_ranks[i] for i in ids]
    lin = [lin_ranks[i] for i in ids]

    print("\n" + "=" * 72)
    print("LINEAGE OFFLINE PROBE (deterministic — no LLM, no DB)")
    print("=" * 72)
    print(f"  Evaluable: {len(ids)}")
    print(f"  {'variant':10s}  @5    @10   @15")
    print(f"  {'baseline':10s}  {recall_at_k(base,5):>4.0%}  {recall_at_k(base,10):>4.0%}  {recall_at_k(base,15):>4.0%}")
    print(f"  {'lineage':10s}  {recall_at_k(lin,5):>4.0%}  {recall_at_k(lin,10):>4.0%}  {recall_at_k(lin,15):>4.0%}")

    print("\n  Target granularity misses (did lineage rescue them?):")
    print(f"    {'id':10s} {'ref':22s} {'base':>5} {'lineage':>8}")
    for q in questions:
        if q.get("id") in _TARGET_MISSES:
            b = base_ranks[q["id"]]; l = lin_ranks[q["id"]]
            print(f"    {q['id']:10s} {q['rule_reference']:22s} "
                  f"{(b if b is not None else '--')!s:>5} {(l if l is not None else '--')!s:>8}")

    moved = []
    for i in ids:
        b, l = base_ranks[i], lin_ranks[i]
        b5 = b is not None and b <= 5
        l5 = l is not None and l <= 5
        if b5 != l5:
            moved.append(f"{i}: {'@5 gained' if l5 else '@5 LOST'} (base={b}, lin={l})")
    print(f"\n  Net @5 movements: {moved or 'none'}")
    print("=" * 72)


def main():
    from sentence_transformers import SentenceTransformer
    print("Building baseline + lineage corpora from disk...")
    base_chunks = _all_chunks(build_chunks)
    lin_chunks = _all_chunks(_build_lineage_chunks)
    print(f"  baseline: {len(base_chunks)} chunks | lineage: {len(lin_chunks)} chunks")

    questions = _load_evaluable()
    print(f"  {len(questions)} evaluable questions.")

    print("Loading BAAI/bge-m3 (~5-10s)...")
    model = SentenceTransformer("BAAI/bge-m3")

    print("Embedding baseline corpus...")
    base_ranks = _measure(model, base_chunks, questions)
    print("Embedding lineage corpus...")
    lin_ranks = _measure(model, lin_chunks, questions)

    _report(base_ranks, lin_ranks, questions)


if __name__ == "__main__":
    main()
