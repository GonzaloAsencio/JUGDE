"""Integration test for scripts._common.get_connection against real Postgres.

This is the whole point of extracting the helper: the shared connection code
now has ONE test covering all the scripts that use it, instead of each script's
copy being untested.
"""
import os

import pytest

from scripts._common import get_connection

pytestmark = pytest.mark.integration


def test_get_connection_connects_and_registers_vector(pg_dsn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    # get_connection() calls register_vector, which looks up the 'vector' type
    # OID and raises if the extension is missing — so a successful connect is
    # itself proof register_vector worked.
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone()[0] == 1
            # Vector round-trips. Cast to text in SQL so the assertion doesn't
            # depend on how the pgvector-python version adapts it back (numpy
            # array vs Vector object).
            cur.execute("SELECT '[1,2,3]'::vector::text")
            assert cur.fetchone()[0] == "[1,2,3]"
    finally:
        conn.close()


def test_get_connection_without_database_url_exits(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        get_connection()
