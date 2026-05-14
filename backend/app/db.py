from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from pgvector.psycopg2 import register_vector


def init_pool(database_url: str, minconn: int = 1, maxconn: int = 5) -> SimpleConnectionPool:
    """Create a psycopg2 connection pool."""
    return SimpleConnectionPool(minconn, maxconn, dsn=database_url)


def close_pool(pool: SimpleConnectionPool) -> None:
    """Close all connections in the pool."""
    pool.closeall()


@contextmanager
def get_conn(pool: SimpleConnectionPool) -> Iterator[psycopg2.extensions.connection]:
    """Yield a connection from the pool with pgvector registered; auto-return on exit."""
    conn = pool.getconn()
    try:
        register_vector(conn)
        yield conn
    finally:
        pool.putconn(conn)
