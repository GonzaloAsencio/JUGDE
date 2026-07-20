"""Shared infra for the corpus-build / maintenance scripts.

Several scripts each re-implemented the same psycopg2 connection (+ pgvector
registration) and SentenceTransformer load. Centralize both so a change to the
connection or embedder policy lives in one place instead of N copies.

Scripts still own their own ``load_dotenv()`` — these helpers read the
environment at call time, they do not load it.
"""
import os

import psycopg2
from pgvector.psycopg2 import register_vector

EMBED_MODEL = "BAAI/bge-m3"


def get_connection(*, register_vectors: bool = True):
    """Open a psycopg2 connection to ``DATABASE_URL``.

    pgvector is registered by default: scripts that read/write embeddings need
    it, and it is harmless for the rest (the corpus DB always has the vector
    extension). Exits with a clear message when ``DATABASE_URL`` is unset.
    """
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL no configurada en .env")
    conn = psycopg2.connect(dsn)
    if register_vectors:
        register_vector(conn)
    return conn


def load_embedder(model_name: str = EMBED_MODEL):
    """Load the SentenceTransformer used to embed corpus text / queries.

    Imported lazily so scripts that only touch the DB don't pay the heavy import.
    """
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)
