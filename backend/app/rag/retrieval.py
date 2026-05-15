from dataclasses import dataclass

from psycopg2.pool import SimpleConnectionPool

from app.db import get_conn
from app.observability import observe_or_noop


@dataclass(frozen=True)
class Chunk:
    id: str
    content: str
    section: str
    parent_section: str | None
    source_type: str
    similarity: float


_SQL = """
SELECT id, content, section, parent_section, source_type,
       1 - (embedding <=> %s::vector) AS similarity
FROM corpus_chunks
WHERE corpus_version = %s
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

_FTS_SQL = """
SELECT id, content, section, parent_section, source_type
FROM corpus_chunks
WHERE corpus_version = %s
  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', %s)
ORDER BY ts_rank_cd(to_tsvector('simple', content), plainto_tsquery('simple', %s)) DESC
LIMIT %s;
"""


def vector_search(
    pool: SimpleConnectionPool,
    embedding: list[float],
    corpus_version: str,
    top_k: int = 5,
) -> list[Chunk]:
    """Return top-K most similar chunks using cosine similarity on the pgvector column."""
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(_SQL, (embedding, corpus_version, embedding, top_k))
            rows = cur.fetchall()

    return [
        Chunk(
            id=str(row[0]),
            content=row[1],
            section=row[2],
            parent_section=row[3],
            source_type=row[4],
            similarity=float(row[5]),
        )
        for row in rows
    ]


def fts_search(
    pool: SimpleConnectionPool,
    query_text: str,
    corpus_version: str,
    top_k: int = 5,
) -> list[Chunk]:
    """Full-text search over corpus_chunks using plainto_tsquery('simple', query_text).

    Returns Chunks ordered by ts_rank_cd desc. similarity is set to 0.0 because
    FTS rank is not comparable to cosine similarity. Empty query_text or zero
    matches returns [] without raising.
    """
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(_FTS_SQL, (corpus_version, query_text, query_text, top_k))
            rows = cur.fetchall()

    return [
        Chunk(
            id=str(row[0]),
            content=row[1],
            section=row[2],
            parent_section=row[3],
            source_type=row[4],
            similarity=0.0,
        )
        for row in rows
    ]


def _rrf_fuse(
    vector_results: list[Chunk],
    fts_results: list[Chunk],
    rrf_k: int,
    top_k: int,
) -> list[Chunk]:
    """Reciprocal Rank Fusion of two ranked Chunk lists.

    For each chunk d, score(d) = sum over lists l in {vector, fts} of
    1 / (rrf_k + rank_l(d)), where rank_l(d) is 1-based (only counted if d
    appears in l).

    Dedup key: chunk.id.
    Tie-break: chunk that appeared in vector_results wins (stable).
    Preserves original similarity from vector side; FTS-only chunks keep 0.0.
    Truncates to top_k.
    """
    # Build score accumulators and canonical Chunk objects.
    # We track whether a chunk came from vector to apply tie-break.
    scores: dict[str, float] = {}
    chunks_by_id: dict[str, Chunk] = {}
    in_vector: set[str] = set()

    for rank_0, chunk in enumerate(vector_results):
        rank = rank_0 + 1  # 1-based
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank)
        chunks_by_id[chunk.id] = chunk  # vector side wins for Chunk object
        in_vector.add(chunk.id)

    for rank_0, chunk in enumerate(fts_results):
        rank = rank_0 + 1  # 1-based
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (rrf_k + rank)
        if chunk.id not in chunks_by_id:
            chunks_by_id[chunk.id] = chunk  # FTS-only: use FTS chunk (similarity=0.0)

    # Sort: descending score; tie-break: vector-side chunks first (stable)
    def sort_key(chunk_id: str) -> tuple:
        return (-scores[chunk_id], 0 if chunk_id in in_vector else 1)

    sorted_ids = sorted(scores.keys(), key=sort_key)
    return [chunks_by_id[cid] for cid in sorted_ids[:top_k]]


def _hybrid_search_impl(
    pool: SimpleConnectionPool,
    embedding: list[float],
    query_text: str,
    corpus_version: str,
    top_k: int = 5,
    top_k_fetch: int = 15,
    rrf_k: int = 60,
) -> list[Chunk]:
    vec_results = vector_search(pool, embedding, corpus_version, top_k=top_k_fetch)
    fts_results = fts_search(pool, query_text, corpus_version, top_k=top_k_fetch)
    return _rrf_fuse(vec_results, fts_results, rrf_k, top_k)


hybrid_search = observe_or_noop(_hybrid_search_impl, name="retrieval")
