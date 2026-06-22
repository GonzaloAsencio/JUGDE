"""Retrieval recall probe — measures whether the gold rule is retrieved, at
what rank, and which sources dominate, WITHOUT an LLM (embedder + DB only).

Why this exists: re-running the full eval costs Gemini credits and the judge is
noisy. This probe isolates retrieval — it separates "the rule was never
retrieved" (chunking/embedding problem) from "retrieved but ranked too low"
(ranking problem), so we know which lever to pull before spending on a full
eval run.

Usage (from backend/):
    python -m scripts.retrieval_probe

Requires: DATABASE_URL + corpus ingestado. Does NOT require GEMINI_API_KEY.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import fts_search, hybrid_search, vector_search
from app.rag.rules import extract_rule_codes
from scripts.eval_judge import _parse_refs, _rule_codes_cover

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

# Pull a deep slice so we can measure recall@5 and recall@15 in one shot, with
# enough fetch headroom for the RRF fusion to settle before truncation.
TOP_K = 15
TOP_K_FETCH = 30


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_retrieval_probe.py — no DB, no network)
# ---------------------------------------------------------------------------

def chunk_covers_refs(refs: list[str], rule_codes, source_type: str) -> bool:
    """True if a chunk covers ANY of the gold refs.

    Errata refs (``errata/...``) are covered only by an errata-source chunk —
    they have no numeric lineage. Numeric refs are covered via rule-code lineage
    (a chunk listing ``103`` covers ``103.2`` and vice versa).
    """
    for ref in refs:
        if ref.startswith("errata/"):
            if source_type == "errata":
                return True
        elif _rule_codes_cover(ref, rule_codes):
            return True
    return False


def first_covering_rank(refs: list[str], chunks) -> int | None:
    """1-based rank of the first chunk covering the gold ref, or None if absent.

    *chunks* is the ordered retrieval result; each needs ``.content`` and
    ``.source_type``. Rule codes are extracted from the FULL content, mirroring
    how the production pipeline derives a chunk's covered rules.
    """
    for rank, chunk in enumerate(chunks, 1):
        codes = extract_rule_codes(chunk.content)
        if chunk_covers_refs(refs, codes, chunk.source_type):
            return rank
    return None


def recall_at_k(ranks: list[int | None], k: int) -> float:
    """Fraction of questions whose gold rule landed within rank *k*.

    None (never retrieved) and ranks beyond k both count as misses.
    """
    if not ranks:
        return 0.0
    hits = sum(1 for r in ranks if r is not None and r <= k)
    return hits / len(ranks)


def source_distribution(source_types: list[str]) -> dict:
    """Count of each source_type in a result slice (e.g. the top-5)."""
    return dict(Counter(source_types))


# ---------------------------------------------------------------------------
# DB-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_evaluable() -> list[dict]:
    """Eval questions that carry a rule_reference (the recall-evaluable ones)."""
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    questions = data["questions"] if isinstance(data, dict) and "questions" in data else data
    return [q for q in questions if q.get("rule_reference") is not None]


def _resolve_corpus_version(pool, settings: Settings) -> str:
    if settings.corpus_version and settings.corpus_version != "latest":
        return settings.corpus_version
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
            row = cur.fetchone()
    if row is None or row[0] is None:
        print("WARNING: corpus_chunks is empty — retrieval will return nothing.", file=sys.stderr)
        return "unknown"
    return row[0]


def _strategy_rank(refs, chunks) -> int | None:
    return first_covering_rank(refs, chunks)


def run_probe(questions, embedder, pool, corpus_version) -> list[dict]:
    """Run hybrid/vector/fts retrieval per question and record the gold rank."""
    results = []
    for q in questions:
        refs = _parse_refs(q["rule_reference"])
        embedding = embedder.encode(q["question"])

        hybrid = hybrid_search(
            pool, embedding, q["question"], corpus_version,
            top_k=TOP_K, top_k_fetch=TOP_K_FETCH,
        )
        vector = vector_search(pool, embedding, corpus_version, top_k=TOP_K)
        fts = fts_search(pool, q["question"], corpus_version, top_k=TOP_K)

        rank = _strategy_rank(refs, hybrid)
        top5_sources = source_distribution([c.source_type for c in hybrid[:5]])
        covering = hybrid[rank - 1] if rank is not None else None

        results.append({
            "id": q.get("id", "?"),
            "rule_reference": q["rule_reference"],
            "hybrid_rank": rank,
            "vector_rank": _strategy_rank(refs, vector),
            "fts_rank": _strategy_rank(refs, fts),
            "covering_source": covering.source_type if covering else None,
            "top5_sources": top5_sources,
        })
    return results


def _print_report(results: list[dict]) -> None:
    hybrid_ranks = [r["hybrid_rank"] for r in results]
    vector_ranks = [r["vector_rank"] for r in results]
    fts_ranks = [r["fts_rank"] for r in results]
    total = len(results)

    # The decisive split: retrieved-but-ranked-low (ranking problem) vs
    # never-retrieved-in-15 (chunking/embedding problem).
    retrieved_below_5 = sum(1 for r in hybrid_ranks if r is not None and r > 5)
    missing_in_15 = sum(1 for r in hybrid_ranks if r is None)

    print("\n" + "=" * 64)
    print("RETRIEVAL PROBE (deterministic — no LLM)")
    print("=" * 64)
    print(f"  Evaluable questions : {total}")
    print(f"  {'strategy':8s}  @5    @10   @15   (production ships top_k=5)")
    for name, ranks in (("hybrid", hybrid_ranks), ("vector", vector_ranks), ("fts", fts_ranks)):
        print(f"  {name:8s}  {recall_at_k(ranks, 5):>4.0%}  "
              f"{recall_at_k(ranks, 10):>4.0%}  {recall_at_k(ranks, 15):>4.0%}")
    print()
    print(f"  RANKING problem  (retrieved but rank >5) : {retrieved_below_5}/{total}")
    print(f"  CHUNKING problem (not in top-15 at all)  : {missing_in_15}/{total}")

    agg = Counter()
    for r in results:
        for src, n in r["top5_sources"].items():
            agg[src] += n
    print("\n  Top-5 source distribution (all questions):")
    for src, n in agg.most_common():
        print(f"    {src:12s}: {n}")

    print("\n  Per-question (hybrid rank | vector | fts | covering source):")
    for r in results:
        rk = r["hybrid_rank"] if r["hybrid_rank"] is not None else "--"
        vk = r["vector_rank"] if r["vector_rank"] is not None else "--"
        fk = r["fts_rank"] if r["fts_rank"] is not None else "--"
        print(f"    {r['id']:10s} ref={r['rule_reference']:<24s} "
              f"h={rk!s:>3} v={vk!s:>3} f={fk!s:>3}  {r['covering_source'] or '-'}")
    print("=" * 64)


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
    print("  Embedder ready.\n")

    try:
        results = run_probe(questions, embedder, pool, corpus_version)
    finally:
        close_pool(pool)

    _print_report(results)


if __name__ == "__main__":
    main()
