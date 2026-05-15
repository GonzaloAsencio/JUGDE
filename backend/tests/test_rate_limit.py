"""Integration tests for rate limiting on POST /api/v1/query.

Run in a single process — in-memory limiter state is deterministic.
"""
import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.rag.retrieval import Chunk
from tests.conftest import FakeEmbedder, FakeGeminiClient, _fake_settings


def _make_chunk() -> Chunk:
    return Chunk(
        id="chunk-1",
        content="Rules content.",
        section="Rules",
        parent_section=None,
        source_type="rulebook",
        similarity=0.9,
    )


@pytest.fixture
def rate_limit_client():
    """Client with rate limiting enabled and per-minute limit of 3 for tests."""
    from app.api.v1.query import get_db_pool, get_embedder, get_gemini_client
    from app.middleware.rate_limit import limiter
    from app.main import app

    # Reset the in-memory limiter storage before each test
    limiter._storage.reset()  # type: ignore[attr-defined]

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: MagicMock()
    app.dependency_overrides[get_gemini_client] = lambda: FakeGeminiClient()

    settings = _fake_settings()
    settings.rate_limit_enabled = True

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=FakeGeminiClient()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


def test_rate_limit_429_on_11th_request(rate_limit_client: TestClient):
    """The 11th request within 1 minute must return 429 with Retry-After."""
    with (
        patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]),
        patch("app.rag.pipeline.call_gemini", return_value="Answer."),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        for i in range(10):
            resp = rate_limit_client.post("/api/v1/query", json={"question": f"Question {i + 1}?"})
            assert resp.status_code == 200, f"Request {i + 1} unexpectedly failed: {resp.status_code}"

        resp = rate_limit_client.post("/api/v1/query", json={"question": "Question 11?"})

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_health_exempt_after_rate_limit(rate_limit_client: TestClient):
    """GET /health must succeed even when the query rate limit is exceeded."""
    with (
        patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]),
        patch("app.rag.pipeline.call_gemini", return_value="Answer."),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        for _ in range(11):
            rate_limit_client.post("/api/v1/query", json={"question": "Exhaust the limit?"})

    resp = rate_limit_client.get("/health")
    assert resp.status_code == 200
