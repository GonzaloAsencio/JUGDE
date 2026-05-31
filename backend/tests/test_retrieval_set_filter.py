"""TDD: set_filter opcional filtra por expansión (incluyendo siempre 'core')."""
from contextlib import contextmanager
from unittest.mock import MagicMock


def _make_conn_ctx(rows):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.__enter__ = lambda s: s
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = lambda s: s
    conn.__exit__ = MagicMock(return_value=False)

    @contextmanager
    def fake_get_conn(_pool):
        yield conn

    return fake_get_conn, cur


# --- vector_search ---------------------------------------------------------

def test_vector_search_without_set_filter_has_no_metadata_clause(monkeypatch):
    fake_conn, cur = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import vector_search
    vector_search(MagicMock(), [0.1, 0.2], "v1", top_k=5)

    sql = cur.execute.call_args[0][0]
    assert "metadata->>'set'" not in sql


def test_vector_search_with_set_filter_adds_clause_and_includes_core(monkeypatch):
    fake_conn, cur = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import vector_search
    vector_search(MagicMock(), [0.1, 0.2], "v1", top_k=5, set_filter="origins")

    sql = cur.execute.call_args[0][0]
    params = cur.execute.call_args[0][1]
    assert "metadata->>'set'" in sql
    assert "'core'" in sql  # core siempre incluido
    assert "origins" in params


# --- fts_search ------------------------------------------------------------

def test_fts_search_without_set_filter_has_no_metadata_clause(monkeypatch):
    fake_conn, cur = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    fts_search(MagicMock(), "query", "v1", top_k=5)

    sql = cur.execute.call_args[0][0]
    assert "metadata->>'set'" not in sql


def test_fts_search_with_set_filter_adds_clause_and_includes_core(monkeypatch):
    fake_conn, cur = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    fts_search(MagicMock(), "query", "v1", top_k=5, set_filter="spiritforged")

    sql = cur.execute.call_args[0][0]
    params = cur.execute.call_args[0][1]
    assert "metadata->>'set'" in sql
    assert "'core'" in sql
    assert "spiritforged" in params


# --- hybrid_search propaga el filtro --------------------------------------

def test_hybrid_search_forwards_set_filter(monkeypatch):
    captured = {}

    def fake_vector(pool, emb, ver, top_k=5, set_filter=None):
        captured["vector"] = set_filter
        return []

    def fake_fts(pool, q, ver, top_k=5, set_filter=None):
        captured["fts"] = set_filter
        return []

    monkeypatch.setattr("app.rag.retrieval.vector_search", fake_vector)
    monkeypatch.setattr("app.rag.retrieval.fts_search", fake_fts)

    from app.rag.retrieval import hybrid_search
    hybrid_search(MagicMock(), [0.1], "q", "v1", top_k=5, set_filter="unleashed")

    assert captured["vector"] == "unleashed"
    assert captured["fts"] == "unleashed"
