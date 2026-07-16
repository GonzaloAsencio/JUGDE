"""EXPERIMENT (LLM-free): does an FTS-keyword arm rescue the semantic-gap misses?

Lever 1 of plan perf/retrieval-misses. The plain hybrid FTS arm is dormant
because plainto_tsquery over a full natural-language question ANDs every token
and matches nothing. This probe instead extracts salient terms from the question
and runs an OR full-text query over them, then RRF-fuses that arm with the vector
arm — measuring recall@5/@10/@15 for vector-only vs fts-keyword-only vs fused.

Nothing here touches production: it reads existing chunk content (no re-ingest,
no re-embed) and never mutates the DB. Only a winning result gets ported to
app/rag/retrieval.py in Phase 2.

Usage (from backend/):
    python -m scripts.fts_keyword_probe

Requires DATABASE_URL + ingested corpus. Never SPENDS Gemini quota, but the key
must be PRESENT — Settings() fails closed without it. Zero quota, not zero config.
"""
import re
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import Chunk, _rrf_fuse, vector_search
from scripts.eval_judge import _parse_refs
from scripts.retrieval_probe import (
    _load_evaluable,
    _resolve_corpus_version,
    first_covering_rank,
    recall_at_k,
)

TOP_K = 15
TOP_K_FETCH = 30

# Misses Phase 0 classified as (B) semantic gap — the target of this lever.
_TARGET_MISSES = {"eval-007", "eval-013", "eval-021"}

# Conversational glue + game-agnostic filler. We DON'T strip card/mechanic nouns;
# those are exactly the salient terms FTS should match against rule text.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "can", "could", "will", "would", "should", "may", "might", "must",
    "i", "you", "he", "she", "it", "we", "they", "me", "my", "your", "his",
    "her", "its", "our", "their", "this", "that", "these", "those", "what",
    "which", "who", "whom", "when", "where", "why", "how", "with", "for",
    "from", "by", "as", "into", "than", "then", "so", "same", "another",
    "one", "two", "both", "any", "all", "some", "no", "not", "during", "while",
    "before", "after", "still", "also", "does", "have", "has", "had", "get",
    "gets", "got", "wins", "win", "card", "cards", "player", "opponent",
    "turn", "game", "play", "plays", "played", "playing", "try", "tries",
}

_WORD = re.compile(r"[A-Za-z]+")


def extract_keywords(question: str) -> list[str]:
    """Salient terms for an FTS-OR query: alphabetic tokens length>=3 minus
    conversational stopwords, de-duplicated preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for tok in _WORD.findall(question.lower()):
        if len(tok) >= 3 and tok not in _STOPWORDS and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


# OR full-text query: any salient term matching the chunk counts. This is the
# whole point — ANDing (plainto_tsquery) is why the dormant arm scores zero.
_FTS_OR_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND to_tsvector('simple', content) @@ to_tsquery('simple', %s)
ORDER BY ts_rank_cd(to_tsvector('simple', content), to_tsquery('simple', %s)) DESC
LIMIT %s;
"""


def fts_keyword_search(pool, keywords, corpus_version, top_k=TOP_K) -> list[Chunk]:
    if not keywords:
        return []
    tsquery = " | ".join(keywords)
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(_FTS_OR_SQL, (corpus_version, tsquery, tsquery, top_k))
            rows = cur.fetchall()
    return [
        Chunk(id=str(r[0]), content=r[1], section=r[2], parent_section=r[3],
              source_type=r[4], metadata=r[5], similarity=0.0)
        for r in rows
    ]


def run(questions, embedder, pool, corpus_version):
    rows = []
    for q in questions:
        refs = _parse_refs(q["rule_reference"])
        kws = extract_keywords(q["question"])
        emb = embedder.encode(q["question"])

        vec = vector_search(pool, emb, corpus_version, top_k=TOP_K_FETCH)
        fts = fts_keyword_search(pool, kws, corpus_version, top_k=TOP_K_FETCH)
        fused = _rrf_fuse(vec, fts, rrf_k=60, top_k=TOP_K)

        rows.append({
            "id": q.get("id", "?"),
            "ref": q["rule_reference"],
            "keywords": kws,
            "vec_rank": first_covering_rank(refs, vec[:TOP_K]),
            "fts_rank": first_covering_rank(refs, fts[:TOP_K]),
            "fused_rank": first_covering_rank(refs, fused),
        })
    return rows


def _report(rows):
    def col(key):
        return [r[key] for r in rows]

    print("\n" + "=" * 72)
    print("FTS-KEYWORD ARM EXPERIMENT (deterministic — no LLM)")
    print("=" * 72)
    print(f"  Evaluable: {len(rows)}")
    print(f"  {'arm':16s}  @5    @10   @15")
    for name, key in (("vector", "vec_rank"), ("fts-keyword", "fts_rank"),
                      ("fused", "fused_rank")):
        ranks = col(key)
        print(f"  {name:16s}  {recall_at_k(ranks, 5):>4.0%}  "
              f"{recall_at_k(ranks, 10):>4.0%}  {recall_at_k(ranks, 15):>4.0%}")

    print("\n  Target semantic-gap misses (did the arm rescue them?):")
    print(f"    {'id':10s} {'ref':20s} {'vec':>4} {'fts':>4} {'fused':>5}")
    for r in rows:
        if r["id"] in _TARGET_MISSES:
            v = r["vec_rank"] if r["vec_rank"] is not None else "--"
            f = r["fts_rank"] if r["fts_rank"] is not None else "--"
            fu = r["fused_rank"] if r["fused_rank"] is not None else "--"
            print(f"    {r['id']:10s} {r['ref']:20s} {v!s:>4} {f!s:>4} {fu!s:>5}")
            print(f"      keywords: {', '.join(r['keywords'])}")

    # Regression guard: any question that vector retrieved but fusion lost.
    lost = [r["id"] for r in rows
            if r["vec_rank"] is not None and r["vec_rank"] <= 5
            and (r["fused_rank"] is None or r["fused_rank"] > 5)]
    print(f"\n  Regressions (vector@5 hit lost after fusion): {lost or 'none'}")
    print("=" * 72)


def main():
    print("Loading evaluable eval questions...")
    questions = _load_evaluable()
    print(f"  {len(questions)} questions.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder (~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Ready.\n")

    try:
        rows = run(questions, embedder, pool, corpus_version)
    finally:
        close_pool(pool)

    _report(rows)


if __name__ == "__main__":
    main()
