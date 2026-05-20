"""Unit tests for add_corpus_v1_2_0 migration script."""
import sys
from unittest.mock import MagicMock, patch


def _run_migration(database_url: str = "postgresql://fake"):
    if "scripts.add_corpus_v1_2_0" in sys.modules:
        del sys.modules["scripts.add_corpus_v1_2_0"]
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    mock_cur.rowcount = 150
    with patch("psycopg2.connect", return_value=mock_conn), \
         patch.dict("os.environ", {"DATABASE_URL": database_url}):
        import scripts.add_corpus_v1_2_0  # noqa: F401
    return mock_conn, mock_cur


def test_migration_inserts_non_rulebook_chunks_from_v1_1_0():
    _, mock_cur = _run_migration()
    sql = mock_cur.execute.call_args[0][0]
    assert "v1.1.0" in sql
    assert "v1.2.0" in sql
    assert "rulebook" in sql


def test_migration_commits_transaction():
    mock_conn, _ = _run_migration()
    mock_conn.commit.assert_called_once()


def test_migration_closes_connection():
    mock_conn, _ = _run_migration()
    mock_conn.close.assert_called_once()
