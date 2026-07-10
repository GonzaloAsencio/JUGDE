"""Unit tests for the cross-encoder reranker (app.rag.reranker).

CrossEncoder is ALWAYS mocked here — never load the real ~80MB model in tests
or CI.
"""
from unittest.mock import MagicMock

import pytest

from app.rag.retrieval import Chunk


def _chunk(chunk_id: str, content: str = "some rule text") -> Chunk:
    return Chunk(
        id=chunk_id,
        content=content,
        section=f"Section {chunk_id}",
        parent_section=None,
        source_type="rulebook",
        similarity=0.5,
    )


@pytest.fixture(autouse=True)
def _reset_singleton():
    """The reranker model is a module-level lazy singleton — reset it between
    tests so each test controls whether/how many times it "loads"."""
    import app.rag.reranker as reranker_module

    reranker_module._model = None
    yield
    reranker_module._model = None


def test_rerank_orders_chunks_by_mocked_predict_score(monkeypatch):
    from app.rag import reranker

    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]

    fake_model = MagicMock()
    fake_model.predict.return_value = [0.1, 0.9, 0.5]  # b > c > a
    monkeypatch.setattr(reranker, "_get_model", lambda model_name: fake_model)

    result = reranker.rerank("query", chunks, top_k=3)

    assert [c.id for c in result] == ["b", "c", "a"]


def test_rerank_truncates_to_top_k():
    from app.rag import reranker

    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]

    class _FakeModel:
        def predict(self, pairs):
            return [0.3, 0.9, 0.1]

    import app.rag.reranker as reranker_module
    reranker_module._model = _FakeModel()

    result = reranker.rerank("query", chunks, top_k=2)

    assert [c.id for c in result] == ["b", "a"]


def test_rerank_never_raises_falls_back_to_input_order_truncated(monkeypatch):
    from app.rag import reranker

    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]

    def _boom(model_name):
        raise RuntimeError("model load failed")

    monkeypatch.setattr(reranker, "_get_model", _boom)

    result = reranker.rerank("query", chunks, top_k=2)

    assert [c.id for c in result] == ["a", "b"], "must degrade to input order, truncated to top_k"


def test_rerank_predict_raises_falls_back_to_input_order():
    from app.rag import reranker

    chunks = [_chunk("a"), _chunk("b")]

    class _BoomModel:
        def predict(self, pairs):
            raise RuntimeError("predict failed")

    import app.rag.reranker as reranker_module
    reranker_module._model = _BoomModel()

    result = reranker.rerank("query", chunks, top_k=5)

    assert [c.id for c in result] == ["a", "b"]


def test_rerank_empty_chunks_returns_empty_list():
    from app.rag import reranker

    assert reranker.rerank("query", [], top_k=5) == []


def test_rerank_model_loaded_lazily_exactly_once_across_repeated_calls(monkeypatch):
    """CrossEncoder constructor must be called at most once across repeated
    rerank() invocations — the lazy singleton must not reload the model."""
    from app.rag import reranker

    construct_calls: list[str] = []

    class _FakeCrossEncoder:
        def __init__(self, model_name):
            construct_calls.append(model_name)

        def predict(self, pairs):
            return [0.0] * len(pairs)

    fake_module = MagicMock()
    fake_module.CrossEncoder = _FakeCrossEncoder
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake_module)

    chunks = [_chunk("a"), _chunk("b")]
    reranker.rerank("q1", chunks, top_k=2)
    reranker.rerank("q2", chunks, top_k=2)
    reranker.rerank("q3", chunks, top_k=2)

    assert len(construct_calls) == 1, "CrossEncoder must be constructed once and reused"
