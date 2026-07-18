"""GATE 3.11.2b (LLM-free): can the FTS-keyword arm reach eval-037's missing refs?

Pre-committed rule (docs/improvement-plan.md, 2026-07-18): lever (c) DIES for
eval-037 if the FTS arm brings NEITHER `131.4` nor `425` into its top-15 under
either tsquery config (`simple`, `english`), OR if the fused arm that does
carry them loses >=1 question the vector arm hits @5 today (the lever-(d)
shape: a headline hiding a regression). It LIVES only bringing >=1 ref with
zero regressions — and even then the next step is a flagged arm with its own
gate, not a ship.

Measurement is PER MISSING REF (per_ref_ranks — the unit 6.1 fixed), never
ANY-ref. Nothing here touches production or mutates the DB; zero LLM calls
(the local embedder run is CPU-only).

Usage (from backend/):
    python -m scripts.fts_term_probe
"""
from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import Chunk, _rrf_fuse, vector_search
from scripts.eval_judge import _parse_refs
from scripts.fts_keyword_probe import extract_keywords
from scripts.retrieval_probe import (
    _load_evaluable,
    _resolve_corpus_version,
    first_covering_rank,
    per_ref_ranks,
)

TOP_K = 15
TOP_K_FETCH = 30
RRF_K = 60

# The gate's universe: the only remaining class-B gap after the 3.13 re-triage
# (eval-030/039 answer correctly without their refs under gpt-oss).
TARGET_ID = "eval-037"
TARGET_REFS = ["131.4", "425"]

CONFIGS = ("simple", "english")

# Same OR shape as fts_keyword_probe._FTS_OR_SQL, with the tsquery config as a
# parameter so `english` (stemming) gets measured too — the eval-039 gate showed
# `simple` vs `english` changes which question terms reach the gold at all.
# The config is interpolated (to_tsvector regconfig can't be a bind parameter);
# CONFIGS is a closed allowlist, never user input.
_FTS_OR_SQL_TMPL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND to_tsvector('{cfg}', content) @@ to_tsquery('{cfg}', %s)
ORDER BY ts_rank_cd(to_tsvector('{cfg}', content), to_tsquery('{cfg}', %s)) DESC
LIMIT %s;
"""


def fts_search(pool, keywords, corpus_version, cfg, top_k):
    if not keywords:
        return []
    assert cfg in CONFIGS
    tsquery = " | ".join(keywords)
    sql = _FTS_OR_SQL_TMPL.format(cfg=cfg)
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (corpus_version, tsquery, tsquery, top_k))
            rows = cur.fetchall()
    return [
        Chunk(id=str(r[0]), content=r[1], section=r[2], parent_section=r[3],
              source_type=r[4], metadata=r[5], similarity=0.0)
        for r in rows
    ]


def main():
    print("Loading evaluable eval questions...")
    questions = _load_evaluable()
    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  {len(questions)} questions | corpus_version = {corpus_version}")

    print("Loading embedder (~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Ready.\n")

    target = next(q for q in questions if q.get("id") == TARGET_ID)
    kws = extract_keywords(target["question"])
    print(f"{TARGET_ID} keywords: {', '.join(kws)}\n")

    try:
        vec_by_id = {
            q["id"]: vector_search(pool, embedder.encode(q["question"]),
                                   corpus_version, top_k=TOP_K_FETCH)
            for q in questions
        }

        verdict_lives = False
        for cfg in CONFIGS:
            print("=" * 72)
            print(f"CONFIG: {cfg}")
            vec = vec_by_id[TARGET_ID]
            fts = fts_search(pool, kws, corpus_version, cfg, TOP_K_FETCH)
            fused = _rrf_fuse(vec, fts, rrf_k=RRF_K, top_k=TOP_K)

            print(f"  {'ref':10s} {'vec@15':>7} {'fts@15':>7} {'fused@15':>9}")
            fts_hits = 0
            vec_map = per_ref_ranks(TARGET_REFS, vec[:TOP_K])
            fts_map = per_ref_ranks(TARGET_REFS, fts[:TOP_K])
            fused_map = per_ref_ranks(TARGET_REFS, fused)
            for ref in TARGET_REFS:
                print(f"  {ref:10s} {str(vec_map[ref]):>7} {str(fts_map[ref]):>7} {str(fused_map[ref]):>9}")
                if fts_map[ref] is not None:
                    fts_hits += 1

            # Regression guard (same as the eval-039 gate): every question the
            # vector arm hits @5 today must survive fusion.
            lost = []
            for q in questions:
                refs = _parse_refs(q["rule_reference"])
                vec_rank = first_covering_rank(refs, vec_by_id[q["id"]][:TOP_K])
                if vec_rank is None or vec_rank > 5:
                    continue
                q_kws = extract_keywords(q["question"])
                q_fts = fts_search(pool, q_kws, corpus_version, cfg, TOP_K_FETCH)
                q_fused = _rrf_fuse(vec_by_id[q["id"]], q_fts, rrf_k=RRF_K, top_k=TOP_K)
                fused_rank = first_covering_rank(refs, q_fused)
                if fused_rank is None or fused_rank > 5:
                    lost.append(q["id"])
            print(f"  regressions (vector@5 lost after fusion): {lost or 'none'}")

            if fts_hits > 0 and not lost:
                verdict_lives = True
    finally:
        close_pool(pool)

    print("=" * 72)
    print(f"VERDICT: lever (c) {'LIVES' if verdict_lives else 'DIES'} for {TARGET_ID}"
          f" (rule: >=1 target ref in the FTS arm's top-15 AND zero fused regressions)")
    print("=" * 72)


if __name__ == "__main__":
    main()
