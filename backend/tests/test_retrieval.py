"""Unit tests for retrieval: _rrf_fuse (pure), fts_search, hybrid_search."""
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from app.rag.retrieval import Chunk, _rrf_fuse

_RRF_K = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk(id: str = "c1", similarity: float = 0.9) -> Chunk:
    return Chunk(
        id=id,
        content="Some content.",
        section="Section",
        parent_section=None,
        source_type="rulebook",
        similarity=similarity,
    )


def _make_conn_ctx(rows):
    """Return (fake_get_conn, cursor_mock) for monkeypatching get_conn."""
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


# ---------------------------------------------------------------------------
# _rrf_fuse tests (pure, no mocks)
# ---------------------------------------------------------------------------

def test_rrf_chunk_only_in_vector_uses_single_score():
    result = _rrf_fuse([_chunk("a")], [], rrf_k=_RRF_K, top_k=10)
    assert len(result) == 1
    assert result[0].id == "a"


def test_rrf_chunk_in_both_sums_scores():
    result = _rrf_fuse([_chunk("a", 0.9)], [_chunk("a", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert len(result) == 1
    assert result[0].id == "a"


def test_rrf_dedup_by_id():
    result = _rrf_fuse([_chunk("a")], [_chunk("a", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert [c.id for c in result].count("a") == 1


def test_rrf_orders_by_score_desc():
    # "a" in both lists (rank 1 each) → score 2/61; "b" only in vector (rank 2) → 1/62
    result = _rrf_fuse(
        [_chunk("a"), _chunk("b")],
        [_chunk("a", 0.0)],
        rrf_k=_RRF_K,
        top_k=10,
    )
    assert result[0].id == "a"


def test_rrf_tie_break_favors_vector():
    # "v" at rank 1 vector-only; "f" at rank 1 fts-only → tie (same score), vector wins
    result = _rrf_fuse([_chunk("v")], [_chunk("f", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "v"


def test_rrf_truncates_to_top_k():
    chunks = [_chunk(str(i)) for i in range(5)]
    result = _rrf_fuse(chunks, [], rrf_k=_RRF_K, top_k=3)
    assert len(result) == 3


def test_rrf_empty_vector_returns_fts_ordering():
    result = _rrf_fuse([], [_chunk("a", 0.0), _chunk("b", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "a"
    assert result[1].id == "b"


def test_rrf_empty_fts_returns_vector_ordering():
    result = _rrf_fuse([_chunk("a"), _chunk("b", 0.5)], [], rrf_k=_RRF_K, top_k=10)
    assert result[0].id == "a"
    assert result[1].id == "b"


def test_rrf_both_empty_returns_empty():
    assert _rrf_fuse([], [], rrf_k=_RRF_K, top_k=10) == []


def test_rrf_preserves_similarity_from_vector_side():
    # same id in both lists; similarity must come from vector chunk (0.95), not FTS (0.0)
    result = _rrf_fuse([_chunk("a", 0.95)], [_chunk("a", 0.0)], rrf_k=_RRF_K, top_k=10)
    assert result[0].similarity == 0.95


# ---------------------------------------------------------------------------
# fts_search tests (monkeypatch get_conn)
# ---------------------------------------------------------------------------

def test_fts_search_returns_chunks(monkeypatch):
    rows = [("id1", "content one", "Section A", None, "rulebook")]
    fake_conn, _ = _make_conn_ctx(rows)
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    result = fts_search(MagicMock(), "double tap", "v1", top_k=5)

    assert len(result) == 1
    assert result[0].id == "id1"
    assert result[0].similarity == 0.0


def test_fts_search_empty_results_returns_empty_list(monkeypatch):
    fake_conn, _ = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    assert fts_search(MagicMock(), "nothing matches", "v1") == []


def test_fts_search_passes_correct_sql_params(monkeypatch):
    fake_conn, cur = _make_conn_ctx([])
    monkeypatch.setattr("app.rag.retrieval.get_conn", fake_conn)

    from app.rag.retrieval import fts_search
    fts_search(MagicMock(), "test query", "v2", top_k=7)

    args = cur.execute.call_args[0][1]
    assert args == ("v2", "test query", "test query", 7)


def test_fts_search_uses_simple_dictionary():
    from app.rag import retrieval
    assert "'simple'" in retrieval._FTS_SQL
    assert "'english'" not in retrieval._FTS_SQL


# ---------------------------------------------------------------------------
# hybrid_search tests (monkeypatch vector_search and fts_search)
# ---------------------------------------------------------------------------

def test_hybrid_search_calls_both_sides_and_fuses(monkeypatch):
    chunk_v, chunk_f = _chunk("v1"), _chunk("f1", 0.0)
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [chunk_v])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [chunk_f])

    from app.rag.retrieval import hybrid_search
    result = hybrid_search(MagicMock(), [], "test", "v1", top_k=5)

    ids = {c.id for c in result}
    assert "v1" in ids and "f1" in ids


def test_hybrid_search_passes_top_k_fetch_to_each_side(monkeypatch):
    vec_calls, fts_calls = [], []

    def fake_vector(pool, emb, corpus_version, top_k):
        vec_calls.append(top_k)
        return []

    def fake_fts(pool, query_text, corpus_version, top_k):
        fts_calls.append(top_k)
        return []

    monkeypatch.setattr("app.rag.retrieval.vector_search", fake_vector)
    monkeypatch.setattr("app.rag.retrieval.fts_search", fake_fts)

    from app.rag.retrieval import hybrid_search
    hybrid_search(MagicMock(), [], "q", "v1", top_k=5, top_k_fetch=20)

    assert vec_calls == [20] and fts_calls == [20]


def test_hybrid_search_returns_top_k_only(monkeypatch):
    chunks = [_chunk(str(i)) for i in range(10)]
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: chunks)
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    assert len(hybrid_search(MagicMock(), [], "q", "v1", top_k=3)) == 3


def test_hybrid_search_fts_empty_returns_vector_ordering(monkeypatch):
    chunk_a, chunk_b = _chunk("a"), _chunk("b", 0.5)
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [chunk_a, chunk_b])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    result = hybrid_search(MagicMock(), [], "q", "v1", top_k=5)

    assert result[0].id == "a" and result[1].id == "b"


def test_hybrid_search_vector_empty_returns_fts_ordering(monkeypatch):
    chunk_a, chunk_b = _chunk("a", 0.0), _chunk("b", 0.0)
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [chunk_a, chunk_b])

    from app.rag.retrieval import hybrid_search
    result = hybrid_search(MagicMock(), [], "q", "v1", top_k=5)

    assert result[0].id == "a" and result[1].id == "b"


def test_hybrid_search_both_empty_returns_empty(monkeypatch):
    monkeypatch.setattr("app.rag.retrieval.vector_search", lambda *a, **kw: [])
    monkeypatch.setattr("app.rag.retrieval.fts_search", lambda *a, **kw: [])

    from app.rag.retrieval import hybrid_search
    assert hybrid_search(MagicMock(), [], "q", "v1") == []
