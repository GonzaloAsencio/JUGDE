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
    metadata: dict | None = None


_SQL = """
SELECT id, content, section, parent_section, source_type, metadata,
       1 - (embedding <=> %s::vector) AS similarity
FROM corpus_chunks
WHERE corpus_version = %s{set_clause}
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

_FTS_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', %s){set_clause}
ORDER BY ts_rank_cd(to_tsvector('simple', content), plainto_tsquery('simple', %s)) DESC
LIMIT %s;
"""

# Filtro por expansión: incluye SIEMPRE los chunks 'core' (reglas base aplican a
# todos los sets) además del set pedido. Devuelve (cláusula SQL, params).
def _set_clause(set_filter: str | None) -> tuple[str, tuple]:
    if not set_filter:
        return "", ()
    return "\n  AND (metadata->>'set' = %s OR metadata->>'set' = 'core')", (set_filter,)


def vector_search(
    pool: SimpleConnectionPool,
    embedding: list[float],
    corpus_version: str,
    top_k: int = 5,
    set_filter: str | None = None,
) -> list[Chunk]:
    """Return top-K most similar chunks using cosine similarity on the pgvector column."""
    clause, clause_params = _set_clause(set_filter)
    sql = _SQL.format(set_clause=clause)
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (embedding, corpus_version, *clause_params, embedding, top_k))
            rows = cur.fetchall()

    return [
        Chunk(
            id=str(row[0]),
            content=row[1],
            section=row[2],
            parent_section=row[3],
            source_type=row[4],
            metadata=row[5],
            similarity=float(row[6]),
        )
        for row in rows
    ]


def fts_search(
    pool: SimpleConnectionPool,
    query_text: str,
    corpus_version: str,
    top_k: int = 5,
    set_filter: str | None = None,
) -> list[Chunk]:
    """Full-text search over corpus_chunks using plainto_tsquery('simple', query_text).

    Returns Chunks ordered by ts_rank_cd desc. similarity is set to 0.0 because
    FTS rank is not comparable to cosine similarity. Empty query_text or zero
    matches returns [] without raising.
    """
    clause, clause_params = _set_clause(set_filter)
    sql = _FTS_SQL.format(set_clause=clause)
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (corpus_version, query_text, *clause_params, query_text, top_k))
            rows = cur.fetchall()

    return [
        Chunk(
            id=str(row[0]),
            content=row[1],
            section=row[2],
            parent_section=row[3],
            source_type=row[4],
            metadata=row[5],
            similarity=0.0,
        )
        for row in rows
    ]


_OFFICIAL_SOURCES = frozenset({"rulebook", "tournament_rules", "patch_notes", "rules_faq"})
_OFFICIAL_BOOST = 1.05  # official rule sources get a 5% score boost over errata


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

    Rulebook chunks receive a _RULEBOOK_BOOST multiplier so base-rule chunks
    rank above errata chunks when scores are comparable.

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
        boost = _OFFICIAL_BOOST if chunk.source_type in _OFFICIAL_SOURCES else 1.0
        scores[chunk.id] = scores.get(chunk.id, 0.0) + boost / (rrf_k + rank)
        chunks_by_id[chunk.id] = chunk  # vector side wins for Chunk object
        in_vector.add(chunk.id)

    for rank_0, chunk in enumerate(fts_results):
        rank = rank_0 + 1  # 1-based
        boost = _OFFICIAL_BOOST if chunk.source_type in _OFFICIAL_SOURCES else 1.0
        scores[chunk.id] = scores.get(chunk.id, 0.0) + boost / (rrf_k + rank)
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
    set_filter: str | None = None,
) -> list[Chunk]:
    vec_results = vector_search(pool, embedding, corpus_version, top_k=top_k_fetch, set_filter=set_filter)
    fts_results = fts_search(pool, query_text, corpus_version, top_k=top_k_fetch, set_filter=set_filter)
    return _rrf_fuse(vec_results, fts_results, rrf_k, top_k)


hybrid_search = observe_or_noop(_hybrid_search_impl, name="retrieval")


_TAGGED_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND LOWER(section) ILIKE LOWER(%s)
ORDER BY (source_type = 'card') DESC,
         (source_type = 'rulebook') DESC
LIMIT 2
"""


def tagged_lookup(
    pool: SimpleConnectionPool,
    tags: list[str],
    corpus_version: str,
) -> list[Chunk]:
    """Direct lookup by section name. Returns chunks with similarity=1.0."""
    if not tags:
        return []
    results: list[Chunk] = []
    seen_ids: set[str] = set()
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            for tag in tags:
                cur.execute(_TAGGED_SQL, (corpus_version, f"%{tag}%"))
                for row in cur.fetchall():
                    chunk_id = str(row[0])
                    if chunk_id not in seen_ids:
                        seen_ids.add(chunk_id)
                        results.append(Chunk(
                            id=chunk_id,
                            content=row[1],
                            section=row[2],
                            parent_section=row[3],
                            source_type=row[4],
                            metadata=row[5],
                            similarity=1.0,
                        ))
    return results
