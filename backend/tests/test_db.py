"""Unit tests for the connection-pool context manager.

The critical invariant: a connection that raises inside the `with get_conn(...)`
block must be discarded (putconn close=True), never returned healthy to the
pool — otherwise a single DB blip poisons the pool and fails every later request.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.db import get_conn, resolve_corpus_version


def _pool_with_conn():
    pool = MagicMock()
    conn = MagicMock()
    pool.getconn.return_value = conn
    return pool, conn


def test_healthy_connection_is_returned_normally():
    pool, conn = _pool_with_conn()
    with patch("app.db.register_vector"):
        with get_conn(pool) as c:
            assert c is conn
    pool.putconn.assert_called_once_with(conn)
    # No close=True on the happy path.
    assert pool.putconn.call_args.kwargs.get("close") is None


def test_broken_connection_is_closed_not_reused():
    pool, conn = _pool_with_conn()
    with patch("app.db.register_vector"):
        with pytest.raises(RuntimeError):
            with get_conn(pool) as c:
                assert c is conn
                raise RuntimeError("network cut mid-query")
    pool.putconn.assert_called_once_with(conn, close=True)


def test_register_vector_failure_also_discards_connection():
    """Even a failure during setup (register_vector) must not leak a live conn."""
    pool, conn = _pool_with_conn()
    with patch("app.db.register_vector", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            with get_conn(pool):
                pass
    pool.putconn.assert_called_once_with(conn, close=True)


# ---------------------------------------------------------------------------
# resolve_corpus_version
# ---------------------------------------------------------------------------

def _settings_stub(corpus_version):
    s = MagicMock()
    s.corpus_version = corpus_version
    return s


def test_resolve_corpus_version_prefers_pinned_env_value():
    """A pinned corpus_version (not 'latest') wins and never hits the DB."""
    pool = MagicMock()
    result = resolve_corpus_version(pool, _settings_stub("v2.1.0"))
    assert result == "v2.1.0"
    pool.getconn.assert_not_called()  # short-circuit, no DB query


def test_resolve_corpus_version_reads_db_when_latest():
    pool, conn = _pool_with_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ("v3.0.0",)
    with patch("app.db.register_vector"):
        result = resolve_corpus_version(pool, _settings_stub("latest"))
    assert result == "v3.0.0"


def test_resolve_corpus_version_returns_none_when_corpus_empty():
    pool, conn = _pool_with_conn()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (None,)
    with patch("app.db.register_vector"):
        result = resolve_corpus_version(pool, _settings_stub(None))
    assert result is None
