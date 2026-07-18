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
        patch("app.main.genai.Client", return_value=MagicMock()),
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


def test_shallow_health_supports_head(health_client: TestClient):
    """Uptime monitors (e.g. UptimeRobot) send HEAD by default — must not 405."""
    resp = health_client.head("/health")
    assert resp.status_code == 200


def test_shallow_health_has_required_fields(health_client: TestClient):
    resp = health_client.get("/health")
    body = resp.json()
    for field in ("status", "version", "corpus_version", "timestamp"):
        assert field in body, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# /health reports the RUNNING models
#
# Why this exists: on 2026-07-17 the question "which model does prod answer
# with?" had no answer. Nothing exposed it — /health carried version and
# corpus_version, /health/deep carried booleans — and the logs named the model
# from settings rather than from the provider, so they lied whenever the
# openai_compat knobs were left set under llm_provider='gemini'. An operator who
# swaps providers by rate limit could not tell which one was live, and neither
# could a gate. The provider objects are already on app.state; reporting their
# model is free (no I/O, keeps /health shallow).
# ---------------------------------------------------------------------------

def test_shallow_health_reports_the_running_models():
    """Pin the provider config explicitly: conftest._fake_settings() reads the
    developer's .env for unset fields (no _env_file=None), so asserting a model
    the fixture didn't pin means asserting whatever the dev's machine runs —
    this test originally did exactly that and broke the day the .env changed
    provider. The models below are CHOSEN here, not inherited."""
    from app.main import app

    settings = _fake_settings()
    settings.llm_provider = "gemini"
    settings.llm_model = None
    settings.gemini_model = "gemini-flash-lite-latest"
    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=MagicMock()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            body = c.get("/health").json()

    assert "models" in body, "operators must be able to curl the live model"
    # Read off the provider objects, so this cannot report a model that isn't
    # the one answering.
    assert body["models"]["main"] == "gemini-flash-lite-latest"
    assert body["models"]["hard"] == "gemini-3.5-flash"


def test_shallow_health_reports_hard_model_null_when_routing_is_off():
    """hard_provider is None when the flag is off (main.py). The field must say
    so explicitly rather than omit it — an absent key reads as 'unknown', and
    'no hard model' is a fact worth reporting."""
    from app.main import app

    settings = _fake_settings()
    settings.hard_query_routing = False
    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=MagicMock()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            body = c.get("/health").json()

    assert body["models"]["hard"] is None


def test_shallow_health_reports_hyde_config():
    """The 2.1/2.2 flips are env vars whose failure mode is silent (a typo'd
    HYDE_MODEL degrades to raw-only retrieval at call time), so the flip must
    be verifiable by curl. hyde.model must come from the PROVIDER object (the
    authority on what hyde() calls), the skip flag from Settings. Every value
    below is pinned here — _fake_settings reads the dev's .env for unset
    fields (see test_shallow_health_reports_the_running_models)."""
    from app.main import app

    settings = _fake_settings()
    settings.llm_provider = "openai_compat"
    settings.llm_base_url = "https://api.example.test/v1"
    settings.llm_api_key = "fake"
    settings.llm_model = "big-answer-model"
    settings.hyde_model = "small-hyde-writer"
    settings.skip_hyde_when_routed = True
    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=MagicMock()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            body = c.get("/health").json()

    assert body["hyde"] == {"model": "small-hyde-writer", "skip_when_routed": True}


def test_shallow_health_hyde_model_falls_back_to_the_answer_model():
    """Unset hyde_model means the main model writes the passages — that is the
    fact /health must report, not None (None would read as 'HyDE off')."""
    from app.main import app

    settings = _fake_settings()
    settings.llm_provider = "gemini"
    settings.llm_model = None
    settings.gemini_model = "gemini-flash-lite-latest"
    settings.hyde_model = None
    settings.skip_hyde_when_routed = False
    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=MagicMock()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
    ):
        with TestClient(app) as c:
            body = c.get("/health").json()

    assert body["hyde"] == {"model": "gemini-flash-lite-latest", "skip_when_routed": False}


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
