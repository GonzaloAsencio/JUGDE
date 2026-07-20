"""Integration-test harness: a real Postgres + pgvector container.

The rest of the suite mocks the DB, so SQL correctness is never actually
exercised. These fixtures spin up the real thing (via testcontainers), run the
migrations in order, and hand back a pool built with the SAME app.db.init_pool
the app uses — so what the tests exercise is the real connection path,
register_vector and all.

Skips cleanly when Docker is unavailable, so the default `pytest` run on a
machine without Docker stays green.
"""
import glob
import os

import pytest

MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "migrations"))


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def _run_migrations(dsn: str) -> None:
    """Apply every migration in filename order against a fresh DB.

    autocommit so index DDL that can't live in a transaction block still
    applies; each file may hold several statements — psycopg2 runs them all.
    """
    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for path in sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql"))):
                with open(path, encoding="utf-8") as f:
                    cur.execute(f.read())
    finally:
        conn.close()


@pytest.fixture(scope="session")
def pg_dsn():
    if not _docker_available():
        pytest.skip("Docker not available — integration tests need a pgvector container")
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        dsn = pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
        _run_migrations(dsn)
        yield dsn


@pytest.fixture(scope="session")
def pg_pool(pg_dsn):
    from app.db import close_pool, init_pool

    pool = init_pool(pg_dsn, minconn=1, maxconn=4)
    yield pool
    close_pool(pool)


@pytest.fixture
def clean_corpus(pg_pool):
    """Empty corpus_chunks before each test so cases don't leak into each other."""
    from app.db import get_conn

    with get_conn(pg_pool) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE corpus_chunks")
        conn.commit()
    return pg_pool
