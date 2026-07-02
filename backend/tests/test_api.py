"""Smoke tests for POST /api/v1/query."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.rag.retrieval import Chunk


def _make_chunk() -> Chunk:
    return Chunk(
        id="chunk-1",
        content="Content about the rules of the game.",
        section="Game Rules",
        parent_section=None,
        source_type="rulebook",
        similarity=0.92,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path(client: TestClient):
    """POST with valid question returns 200, non-empty answer, and citations list."""
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        resp = client.post("/api/v1/query", json={"question": "How does double-tap work?"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"]  # non-empty string
    assert isinstance(body["citations"], list)
    assert "latency_ms" in body


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

def test_empty_question_returns_422(client: TestClient):
    """POST with empty question string returns 422 (Pydantic validation error)."""
    resp = client.post("/api/v1/query", json={"question": ""})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Timeout → 504
# ---------------------------------------------------------------------------

def test_timeout_returns_504(timeout_client: TestClient):
    """When Gemini raises GenerationTimeout, the endpoint returns 504."""
    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        resp = timeout_client.post(
            "/api/v1/query", json={"question": "What happens on timeout?"}
        )

    assert resp.status_code == 504
    assert resp.json()["detail"] == "Generation timeout"


# ---------------------------------------------------------------------------
# Pool exhaustion → 503 (load shedding)
# ---------------------------------------------------------------------------

def test_pool_exhaustion_returns_503_with_retry_after(client: TestClient):
    """When the connection pool is exhausted (PoolError), shed load with 503."""
    from psycopg2.pool import PoolError

    with patch(
        "app.api.v1.query.answer_question",
        side_effect=PoolError("connection pool exhausted"),
    ):
        resp = client.post("/api/v1/query", json={"question": "Any question here?"})

    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "2"


# ---------------------------------------------------------------------------
# corpus_version re-resolution (ingest after startup, no restart)
# ---------------------------------------------------------------------------

def test_query_reresolves_corpus_version_when_none(client: TestClient):
    """If startup found an empty corpus, a later request re-resolves and serves."""
    from app.rag.schemas import QueryResponse

    client.app.state.corpus_version = None  # simulate empty corpus at startup

    with patch("app.api.v1.query.resolve_corpus_version", return_value="v9") as mock_resolve, \
         patch("app.api.v1.query.answer_question") as mock_answer:
        mock_answer.return_value = QueryResponse(answer="ok", citations=[], latency_ms=1)
        resp = client.post("/api/v1/query", json={"question": "A valid question?"})

    assert resp.status_code == 200
    mock_resolve.assert_called_once()
    assert client.app.state.corpus_version == "v9"  # cached back
    assert mock_answer.call_args.kwargs["corpus_version"] == "v9"


def test_query_still_503_when_corpus_empty_after_reresolve(client: TestClient):
    """If the corpus is still empty after re-resolving, return 503 (not crash)."""
    client.app.state.corpus_version = None

    with patch("app.api.v1.query.resolve_corpus_version", return_value=None):
        resp = client.post("/api/v1/query", json={"question": "A valid question?"})

    assert resp.status_code == 503
