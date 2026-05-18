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
        with patch("app.rag.pipeline.call_llm", return_value="Here is the answer."):
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
