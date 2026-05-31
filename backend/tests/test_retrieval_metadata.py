"""TDD: retrieval lee la columna metadata y la expone en Chunk.metadata."""
from contextlib import contextmanager
from unittest.mock import MagicMock

from app.rag.retrieval import Chunk


def _conn_ctx(rows):
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


def test_chunk_has_metadata_field_default_none():
    c = Chunk(id="a", content="x", section="s", parent_section=None,
              source_type="errata", similarity=0.5)
    assert c.metadata is None


def test_fts_search_populates_metadata(monkeypatch):
    rows = [("id1", "content", "Sec", None, "errata", {"set": "origins"})]
    fake_conn, _ = _conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)
    from app.rag.retrieval import fts_search
    result = fts_search(MagicMock(), "q", "v2", top_k=5)
    assert result[0].metadata == {"set": "origins"}


def test_vector_search_populates_metadata(monkeypatch):
    # vector_search row: id, content, section, parent_section, source_type, metadata, similarity
    rows = [("id1", "content", "Sec", None, "rulebook", {"set": "core"}, 0.87)]
    fake_conn, _ = _conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)
    from app.rag.retrieval import vector_search
    result = vector_search(MagicMock(), [0.0] * 1024, "v2", top_k=5)
    assert result[0].metadata == {"set": "core"}
    assert result[0].similarity == 0.87


def test_tagged_lookup_populates_metadata(monkeypatch):
    rows = [("id1", "## Yasuo", "Yasuo", None, "card", {"set": "origins"})]
    fake_conn, _ = _conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)
    from app.rag.retrieval import tagged_lookup
    result = tagged_lookup(MagicMock(), ["yasuo"], "v2")
    assert result[0].metadata == {"set": "origins"}
