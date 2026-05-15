"""Tests for /health and /health/deep endpoints."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _fake_settings


def _make_health_client():
    from app.main import app

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=MagicMock()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=_fake_settings()),
    ):
        with TestClient(app) as c:
            yield c


@pytest.fixture
def health_client():
    yield from _make_health_client()


def test_shallow_health_returns_200(health_client: TestClient):
    resp = health_client.get("/health")
    assert resp.status_code == 200


def test_shallow_health_has_required_fields(health_client: TestClient):
    resp = health_client.get("/health")
    body = resp.json()
    for field in ("status", "version", "corpus_version", "timestamp"):
        assert field in body, f"Missing field: {field}"


def test_deep_health_returns_200_when_degraded(health_client: TestClient):
    """Even when Redis is unreachable, /health/deep must return HTTP 200."""
    failing_redis = MagicMock()
    failing_redis.ping.side_effect = RuntimeError("connection refused")

    with patch("app.cache._redis_client", failing_redis):
        with patch("app.db.get_conn") as mock_conn:
            cursor_cm = MagicMock()
            cursor_cm.__enter__ = MagicMock(return_value=MagicMock(execute=MagicMock()))
            cursor_cm.__exit__ = MagicMock(return_value=False)

            conn_cm = MagicMock()
            conn_cm.__enter__ = MagicMock(
                return_value=MagicMock(cursor=MagicMock(return_value=cursor_cm))
            )
            conn_cm.__exit__ = MagicMock(return_value=False)
            mock_conn.return_value = conn_cm

            resp = health_client.get("/health/deep")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["redis"] is False
