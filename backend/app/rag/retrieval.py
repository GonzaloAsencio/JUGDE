from dataclasses import dataclass

from psycopg2.pool import SimpleConnectionPool

from app.db import get_conn


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
