"""Keyword-eviction probe — measures whether auto-tagging (_detect_keywords)
evicts semantically-retrieved card chunks from the generator's context, WITHOUT
an LLM (embedder + DB only).

Why this exists: the ruling questions ('specific-card' tag) failed in eval, and a
manual probe traced eval-021 (Brambleback) to auto-detected keywords ('mighty',
'draw', 'equip') firing tagged_lookup, whose lexical sim=0.0 chunks were
prepended and pushed the real card chunks out of the top-k context. This probe
quantifies the damage across all rulings: it compares the semantic baseline
(hybrid_search alone) against the assembled context (the real pipeline path via
_assemble_context) and counts evicted card chunks.

Usage (from backend/):
    python -m scripts.keyword_eviction_probe

Requires: DATABASE_URL + corpus ingestado. Does NOT require GEMINI_API_KEY.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import init_pool, get_conn
from app.rag.embedder import Embedder
from app.rag.pipeline import _assemble_context, _detect_keywords, _extract_tags
from app.rag.retrieval import hybrid_search, tagged_lookup

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"
_RULING_TAG = "specific-card"


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_keyword_eviction_probe.py — no DB)
# ---------------------------------------------------------------------------

def count_card_chunks(chunks) -> int:
    """Number of card-source chunks in a result list."""
    return sum(1 for c in chunks if c.source_type == "card")


def card_eviction(baseline, assembled) -> int:
    """Card chunks present in the semantic baseline but missing from the
    assembled context. Positive = tagging evicted that many card chunks.
    """
    return count_card_chunks(baseline) - count_card_chunks(assembled)


def load_rulings(eval_set_path: Path = _EVAL_SET) -> list[dict]:
    """Ruling questions = those tagged 'specific-card'."""
    data = json.loads(eval_set_path.read_text(encoding="utf-8"))
    qs = data if isinstance(data, list) else data.get("questions", [])
    return [q for q in qs if _RULING_TAG in (q.get("tags") or [])]


# ---------------------------------------------------------------------------
# DB-backed probe
# ---------------------------------------------------------------------------

def run_probe(rulings, embedder, pool, corpus_version, top_k, top_k_fetch, rrf_k) -> list[dict]:
    rows = []
    for q in rulings:
        question = q["question"]
        clean, explicit = _extract_tags(question)
        auto = _detect_keywords(clean or question)
        directed = list(dict.fromkeys(explicit))  # eval has no card_mentions
        auto_only = [t for t in auto if t not in directed]
        explicit_chunks = tagged_lookup(pool, directed, corpus_version) if directed else []
        auto_chunks = tagged_lookup(pool, auto_only, corpus_version) if auto_only else []
        baseline = hybrid_search(
            pool, embedder.encode(clean or question), clean or question,
            corpus_version, top_k=top_k, top_k_fetch=top_k_fetch, rrf_k=rrf_k,
        )
        assembled = _assemble_context(explicit_chunks, baseline, auto_chunks, top_k)
        rows.append({
            "id": q["id"],
            "auto_tags": auto,
            "n_tagged": len(explicit_chunks) + len(auto_chunks),
            "card_base": count_card_chunks(baseline),
            "card_pipe": count_card_chunks(assembled),
            "evicted": card_eviction(baseline, assembled),
            "overflow": len(assembled) - top_k,
        })
    return rows


def main() -> int:
    s = Settings()
    pool = init_pool(s.database_url, 1, 3)
    with get_conn(pool) as c, c.cursor() as cur:
        cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
        corpus_version = cur.fetchone()[0]
    embedder = Embedder.load(s.model_name)

    rulings = load_rulings()
    rows = run_probe(rulings, embedder, pool, corpus_version, s.top_k, s.top_k_fetch, s.rrf_k)

    header = f"{'id':<10}{'auto-tags':<30}{'#tag':>5}{'base':>6}{'pipe':>6}{'evict':>7}{'overflow':>9}"
    print(f"rulings '{_RULING_TAG}': {len(rulings)}\ncorpus_version: {corpus_version}\n")
    print(header)
    print("-" * len(header))
    fires = evicts = lost = 0
    for r in rows:
        if r["n_tagged"]:
            fires += 1
        if r["evicted"] > 0:
            evicts += 1
            lost += r["evicted"]
        tagstr = ",".join(r["auto_tags"])[:28]
        print(f"{r['id']:<10}{tagstr:<30}{r['n_tagged']:>5}{r['card_base']:>6}"
              f"{r['card_pipe']:>6}{r['evicted']:>7}{r['overflow']:>9}")
    print("-" * len(header))
    print(f"\nauto-tagging dispara: {fires}/{len(rows)}")
    print(f"rulings con eviction de carta (>0): {evicts}/{len(rows)}")
    print(f"total chunks de carta perdidos: {lost}")
    print(f"rulings con overflow (>top_k): {sum(1 for r in rows if r['overflow'] > 0)}/{len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
