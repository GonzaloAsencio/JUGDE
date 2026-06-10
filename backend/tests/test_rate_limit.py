"""Integration tests for rate limiting on POST /api/v1/query.

Run in a single process — in-memory limiter state is deterministic.
"""
import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.rag.retrieval import Chunk
from tests.conftest import FakeEmbedder, FakeLLMProvider, _fake_settings


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
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.middleware.rate_limit import limiter
    from app.main import app

    # Reset the in-memory limiter storage before each test
    limiter._storage.reset()  # type: ignore[attr-defined]

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: MagicMock()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    settings = _fake_settings()
    settings.rate_limit_enabled = True

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def proxied_rate_limit_client():
    """Rate-limited client where the proxy shared secret is configured."""
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.middleware.rate_limit import limiter
    from app.main import app

    limiter._storage.reset()  # type: ignore[attr-defined]

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: MagicMock()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    settings = _fake_settings()
    settings.rate_limit_enabled = True
    settings.proxy_shared_secret = "test-secret"

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


def _post(client: TestClient, question: str, headers: dict | None = None):
    with (
        patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        return client.post("/api/v1/query", json={"question": question}, headers=headers or {})


def test_x_real_ip_gives_independent_buckets(proxied_rate_limit_client: TestClient):
    """Each X-Real-IP forwarded by the trusted proxy gets its own rate-limit bucket."""
    secret = {"X-Proxy-Secret": "test-secret"}

    for i in range(10):
        resp = _post(proxied_rate_limit_client, f"Question {i}?", {**secret, "X-Real-IP": "1.1.1.1"})
        assert resp.status_code == 200, f"Request {i + 1} failed: {resp.status_code}"

    resp = _post(proxied_rate_limit_client, "Question 11?", {**secret, "X-Real-IP": "1.1.1.1"})
    assert resp.status_code == 429

    # A different user behind the same proxy must NOT be affected
    resp = _post(proxied_rate_limit_client, "Other user?", {**secret, "X-Real-IP": "2.2.2.2"})
    assert resp.status_code == 200


def test_x_real_ip_ignored_without_configured_secret(rate_limit_client: TestClient):
    """Anti-spoofing: without a trusted proxy, X-Real-IP must not split buckets."""
    for i in range(10):
        resp = _post(rate_limit_client, f"Question {i}?", {"X-Real-IP": "1.1.1.1"})
        assert resp.status_code == 200, f"Request {i + 1} failed: {resp.status_code}"

    # Spoofing a new IP must not grant a fresh bucket
    resp = _post(rate_limit_client, "Spoofed?", {"X-Real-IP": "9.9.9.9"})
    assert resp.status_code == 429


@pytest.fixture
def low_limit_client():
    """Client where settings define a per-minute limit of 3 — the decorator
    must honor settings instead of hardcoding 10/minute."""
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.middleware.rate_limit import limiter
    from app.main import app

    limiter._storage.reset()  # type: ignore[attr-defined]

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: MagicMock()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    settings = _fake_settings()
    settings.rate_limit_enabled = True
    settings.rate_limit_per_min = 3

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
        patch("app.api.v1.query.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


def test_limits_come_from_settings(low_limit_client: TestClient):
    """With rate_limit_per_min=3, the 4th request must hit 429."""
    for i in range(3):
        resp = _post(low_limit_client, f"Question {i}?")
        assert resp.status_code == 200, f"Request {i + 1} failed: {resp.status_code}"

    resp = _post(low_limit_client, "Question 4?")
    assert resp.status_code == 429


def test_rate_limit_429_on_11th_request(rate_limit_client: TestClient):
    """The 11th request within 1 minute must return 429 with Retry-After."""
    with (
        patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]),
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
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        for _ in range(11):
            rate_limit_client.post("/api/v1/query", json={"question": "Exhaust the limit?"})

    resp = rate_limit_client.get("/health")
    assert resp.status_code == 200
