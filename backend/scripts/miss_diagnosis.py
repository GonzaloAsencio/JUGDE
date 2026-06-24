"""Miss diagnosis — drill into the CHUNKING-misses (gold rule NEVER retrieved in
top-15) that the retrieval probe surfaces, WITHOUT an LLM (embedder + DB only).

For each miss it dumps three things and a verdict:
  1. the gold ref(s) and the corpus chunk(s) that actually cover them (proof the
     rule IS in the corpus — this is a retrieval gap, not a corpus gap),
  2. the top-15 vector results actually retrieved (rank, source, section, codes),
  3. a deterministic class:
       (A) granularity — a SIBLING of the gold rule (same 3-digit base, e.g.
           ``383.4.d`` for gold ``383.4.e``) is retrieved but doesn't cover it →
           the sub-rule chunk got separated from its retrievable context.
       (B) semantic gap — nothing from the gold's rule family is retrieved → the
           question's vocabulary is too far from the rule text.
  Note: a chunk listing ``383`` or ``383.4`` already COVERS ``383.4.e`` (lineage),
  so a genuine miss has none of those — class (A) is strictly siblings/cousins.

This class decides the lever (FTS-keyword vs chunk lineage) with NO LLM call.

Usage (from backend/):
    python -m scripts.miss_diagnosis

Requires DATABASE_URL + ingested corpus. Does NOT require GEMINI_API_KEY.
"""
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import vector_search
from app.rag.rules import extract_rule_codes
from scripts.eval_judge import _parse_refs
from scripts.retrieval_probe import (
    _load_evaluable,
    _resolve_corpus_version,
    chunk_covers_refs,
    first_covering_rank,
)

TOP_K = 15
_BASE = re.compile(r"\d{3}")


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_miss_diagnosis.py — no DB, no network)
# ---------------------------------------------------------------------------

def numeric_base(code: str) -> str | None:
    """3-digit base of a rule code: ``383.4.e`` -> ``383``. None for non-numeric
    (e.g. ``errata/...``)."""
    m = _BASE.match(code)
    return m.group(0) if m else None


def classify_miss(refs: list[str], top_chunks) -> str:
    """Classify a miss as ``A:granularity`` or ``B:semantic_gap``.

    Granularity (A): a chunk in *top_chunks* lists a rule sharing the gold's
    3-digit base (same rule family) — it just isn't an ancestor that covers the
    gold sub-rule. Semantic gap (B): no chunk from the gold's family is present.

    *top_chunks* must be a genuine miss (none covers the refs); this only
    inspects the rule FAMILY proximity, not coverage.
    """
    gold_bases = {b for ref in refs if (b := numeric_base(ref)) is not None}
    if not gold_bases:
        return "B:semantic_gap"
    for chunk in top_chunks:
        for code in extract_rule_codes(chunk.content):
            if numeric_base(code) in gold_bases:
                return "A:granularity"
    return "B:semantic_gap"


# ---------------------------------------------------------------------------
# DB-driven diagnosis (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_all_chunks(pool, corpus_version):
    """Every (content, section, source_type) for the active corpus — used to
    locate the chunk that covers a gold ref, proving the rule is ingested."""
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT content, section, source_type FROM corpus_chunks "
                "WHERE corpus_version = %s",
                (corpus_version,),
            )
            return cur.fetchall()


def _covering_chunks(refs, all_chunks):
    """Corpus rows (content, section, source_type) whose codes cover the refs."""
    hits = []
    for content, section, source_type in all_chunks:
        codes = extract_rule_codes(content)
        if chunk_covers_refs(refs, codes, source_type):
            hits.append((content, section, source_type, sorted(codes)))
    return hits


def _print_top15(chunks) -> None:
    for rank, c in enumerate(chunks, 1):
        codes = sorted(extract_rule_codes(c.content))
        codes_str = ", ".join(codes[:8]) + (" …" if len(codes) > 8 else "")
        print(f"    [{rank:2d}] {c.source_type:10s} sim={c.similarity:.3f} "
              f"section={c.section!r}")
        print(f"         codes: {codes_str or '(none)'}")


def diagnose(questions, embedder, pool, corpus_version, all_chunks) -> list[dict]:
    misses = []
    for q in questions:
        refs = _parse_refs(q["rule_reference"])
        embedding = embedder.encode(q["question"])
        top = vector_search(pool, embedding, corpus_version, top_k=TOP_K)
        rank = first_covering_rank(refs, top)
        if rank is not None:
            continue  # retrieved within top-15 — not a chunking-miss

        cls = classify_miss(refs, top)
        misses.append({
            "id": q.get("id", "?"),
            "question": q["question"],
            "refs": refs,
            "rule_reference": q["rule_reference"],
            "top": top,
            "class": cls,
            "covering": _covering_chunks(refs, all_chunks),
        })
    return misses


def _print_report(misses) -> None:
    print("\n" + "=" * 72)
    print("MISS DIAGNOSIS (deterministic — no LLM)")
    print("=" * 72)
    print(f"  CHUNKING-misses found: {len(misses)}\n")

    a = sum(1 for m in misses if m["class"].startswith("A"))
    b = sum(1 for m in misses if m["class"].startswith("B"))
    print(f"  (A) granularity  : {a}  -> lever: chunk lineage")
    print(f"  (B) semantic gap : {b}  -> lever: FTS-keyword arm\n")

    for m in misses:
        print("-" * 72)
        print(f"  {m['id']}  ref={m['rule_reference']}  CLASS={m['class']}")
        print(f"  Q: {m['question']}")
        cov = m["covering"]
        print(f"\n  Gold chunk(s) in corpus that cover the ref: {len(cov)}")
        for content, section, source_type, codes in cov[:3]:
            preview = content.replace("\n", " ")[:160]
            print(f"    - {source_type:10s} section={section!r}")
            print(f"      codes: {', '.join(codes[:10])}")
            print(f"      text : {preview}…")
        if not cov:
            print("    (NONE — would be a real corpus gap, not just retrieval)")
        print(f"\n  Top-15 actually retrieved (vector):")
        _print_top15(m["top"])
    print("=" * 72)


def main() -> None:
    print("Loading evaluable eval questions...")
    questions = _load_evaluable()
    print(f"  {len(questions)} questions with rule_reference.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.")

    print("Loading corpus chunks for gold-chunk lookup...")
    all_chunks = _load_all_chunks(pool, corpus_version)
    print(f"  {len(all_chunks)} chunks in corpus {corpus_version}.\n")

    try:
        misses = diagnose(questions, embedder, pool, corpus_version, all_chunks)
    finally:
        close_pool(pool)

    _print_report(misses)


if __name__ == "__main__":
    main()
