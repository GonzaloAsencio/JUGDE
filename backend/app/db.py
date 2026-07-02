from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from pgvector.psycopg2 import register_vector


def init_pool(database_url: str, minconn: int = 1, maxconn: int = 10) -> ThreadedConnectionPool:
    """Create a thread-safe psycopg2 connection pool.

    ThreadedConnectionPool (not SimpleConnectionPool): the query handler is a
    sync FastAPI endpoint, so it runs across many threadpool workers that call
    getconn/putconn concurrently. SimpleConnectionPool is explicitly not safe to
    share across threads.
    """
    return ThreadedConnectionPool(minconn, maxconn, dsn=database_url)


def close_pool(pool: ThreadedConnectionPool) -> None:
    """Close all connections in the pool."""
    pool.closeall()


@contextmanager
def get_conn(pool: ThreadedConnectionPool) -> Iterator[psycopg2.extensions.connection]:
    """Yield a connection from the pool with pgvector registered; auto-return on exit.

    A connection that errors (dropped DB, network cut mid-query) is discarded
    with ``close=True`` instead of returned: the pool does not health-check on
    putconn, so a poisoned connection would be handed to the next caller and
    fail in cascade until restart. Closing it lets the pool open a fresh one.
    """
    conn = pool.getconn()
    try:
        register_vector(conn)
        yield conn
    except Exception:
        pool.putconn(conn, close=True)
        raise
    else:
        pool.putconn(conn)
