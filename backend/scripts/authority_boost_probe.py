"""Authority-boost tuning probe — deterministic, no LLM.

The production retrieval applies an authority-boost multiplier on the RRF score
(errata > patch_notes > rulebook). A prior probe on corpus v2.0.0 showed the
boost COST recall@5 (raw 47% vs production rrf_110 41%): rewarding errata/patch
pushes rulebook chunks — where the gold rules live — below rank 5.

This probe re-measures that trade-off on the CURRENT corpus (v2.1.0, re-chunked)
across several boost magnitudes, so we can pick the level that keeps the
errata>rulebook ordering benefit without burying rulebook gold. It fetches the
vector slice ONCE per question and re-ranks locally per config (deterministic,
no extra DB round trips, no LLM).

SCOPE — this models the RAW retrieval arm only (single arm, vector vs empty FTS,
one boost application). Production runs fuse_eq: a second HyDE arm is RRF-fused
in and the boost applies again at that fusion. So these numbers are DIRECTIONAL
(less boost → less rulebook demotion), not the exact production recall — confirm
the production effect with a full-pipeline eval (scripts.eval).

Usage (from backend/):
    python -m scripts.authority_boost_probe
"""
from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import Chunk, vector_search
from scripts.eval_judge import _parse_refs
from scripts.retrieval_probe import _load_evaluable, _resolve_corpus_version, first_covering_rank, recall_at_k

TOP_K_FETCH = 30
RRF_K = 60

# Boost configs to compare. {} = no boost (raw vector order). Production today is
# rrf_110 (errata 1.10, patch_notes 1.05). The rest are milder candidates.
CONFIGS = {
    "raw (no boost)":       {},
    "prod rrf_110":         {"errata": 1.10, "patch_notes": 1.05},
    "sim_105":              {"errata": 1.05, "patch_notes": 1.025},
    "sim_102":              {"errata": 1.02, "patch_notes": 1.01},
}


def rank_with_boost(vec_results: list[Chunk], boost: dict, rrf_k: int = RRF_K) -> list[Chunk]:
    """Re-rank a vector result slice by RRF score scaled by the per-source boost.

    Mirrors a SINGLE retrieval arm of the production path (FTS dormant: vector vs
    empty). It does not model the second HyDE arm of fuse_eq — see module docstring.
    """
    scores: dict[str, float] = {}
    by_id: dict[str, Chunk] = {}
    for rank0, ch in enumerate(vec_results):
        b = boost.get(ch.source_type, 1.0)
        scores[ch.id] = b / (rrf_k + rank0 + 1)
        by_id[ch.id] = ch
    order = sorted(scores, key=lambda cid: -scores[cid])
    return [by_id[cid] for cid in order]


def main() -> None:
    print("Loading evaluable eval questions...")
    questions = _load_evaluable()
    print(f"  {len(questions)} questions with rule_reference.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.\n")

    # ranks[config] = list of first-covering ranks (one per question)
    ranks: dict[str, list] = {name: [] for name in CONFIGS}
    try:
        for q in questions:
            refs = _parse_refs(q["rule_reference"])
            embedding = embedder.encode(q["question"])
            vec = vector_search(pool, embedding, corpus_version, top_k=TOP_K_FETCH)
            for name, boost in CONFIGS.items():
                reranked = rank_with_boost(vec, boost)
                ranks[name].append(first_covering_rank(refs, reranked))
    finally:
        close_pool(pool)

    print("=" * 60)
    print(f"AUTHORITY-BOOST PROBE (deterministic) — corpus {corpus_version}")
    print("=" * 60)
    print(f"  {'config':18s}  @5    @10   @15")
    for name in CONFIGS:
        r = ranks[name]
        print(f"  {name:18s}  {recall_at_k(r, 5):>4.0%}  {recall_at_k(r, 10):>4.0%}  {recall_at_k(r, 15):>4.0%}")
    print("=" * 60)


if __name__ == "__main__":
    main()
