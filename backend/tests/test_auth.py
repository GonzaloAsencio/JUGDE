"""Integration tests for shared-secret auth between the Next proxy and the backend.

When settings.proxy_shared_secret is set, every endpoint except shallow /health
requires the X-Proxy-Secret header. When unset, auth is disabled (local dev).
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.rag.retrieval import Chunk
from tests.conftest import FakeEmbedder, FakeLLMProvider, _fake_settings, _reset_limiter

TEST_SECRET = "test-secret"


def _make_chunk() -> Chunk:
    return Chunk(
        id="chunk-1",
        content="Rules content.",
        section="Rules",
        parent_section=None,
        source_type="rulebook",
        similarity=0.9,
    )


def _auth_client(proxy_shared_secret: str | None):
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.main import app

    _reset_limiter()

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: MagicMock()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    settings = _fake_settings()
    settings.proxy_shared_secret = proxy_shared_secret

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
def secured_client():
    yield from _auth_client(TEST_SECRET)


@pytest.fixture
def open_client():
    yield from _auth_client(None)


def _post_query(client: TestClient, headers: dict | None = None):
    with (
        patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        return client.post(
            "/api/v1/query",
            json={"question": "Can a unit attack twice?"},
            headers=headers or {},
        )


def test_query_without_secret_returns_401(secured_client: TestClient):
    resp = _post_query(secured_client)
    assert resp.status_code == 401


def test_query_with_wrong_secret_returns_401(secured_client: TestClient):
    resp = _post_query(secured_client, headers={"X-Proxy-Secret": "wrong"})
    assert resp.status_code == 401


def test_query_with_valid_secret_succeeds(secured_client: TestClient):
    resp = _post_query(secured_client, headers={"X-Proxy-Secret": TEST_SECRET})
    assert resp.status_code == 200


def test_401_detail_is_generic(secured_client: TestClient):
    """The 401 must not reveal that a proxy secret mechanism exists."""
    resp = _post_query(secured_client)
    assert resp.json() == {"detail": "Unauthorized"}


def test_shallow_health_is_exempt(secured_client: TestClient):
    resp = secured_client.get("/health")
    assert resp.status_code == 200


def test_deep_health_requires_secret(secured_client: TestClient):
    resp = secured_client.get("/health/deep")
    assert resp.status_code == 401


def test_deep_health_with_secret_succeeds(secured_client: TestClient):
    resp = secured_client.get("/health/deep", headers={"X-Proxy-Secret": TEST_SECRET})
    assert resp.status_code == 200


def test_auth_disabled_when_secret_unset(open_client: TestClient):
    """Local dev mode: no secret configured means no auth enforcement."""
    resp = _post_query(open_client)
    assert resp.status_code == 200
    assert open_client.get("/health/deep").status_code == 200
