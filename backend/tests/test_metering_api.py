"""Metering enforcement wiring (Fase 5, PR2b) — endpoints, /usage, /health.

Contract under test:
- /query and /query/stream run enforce_quota as a DEPENDENCY: over-quota
  requests 429 with a clean status BEFORE the pipeline runs (a stream must
  never start and then fail in-band for quota).
- The flag only gates the 429: with METERING_ENABLED=false everything passes
  and usage is still recorded (dark counters are how the flip is verified).
- Post-response bookkeeping (Redis + ledger) happens in the endpoint, reading
  QueryResponse.usage — the pipeline never learns identity.
- GET /api/v1/usage reports {used, quota, remaining, resets_at, tier} and
  works with the flag off. /health exposes metering.enabled (pattern #78).
- Fail-open end to end: Redis raising -> the query still answers 200.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.rag.retrieval import Chunk
from app.usage import user_key, global_key
from tests.conftest import FakeEmbedder, FakeLLMProvider, FakePool, _fake_settings, _reset_limiter
from tests.test_metering import _FakeRedis

_CHUNK = Chunk(
    id="abc123", content="Some content about the rules.", section="820. Repeat",
    parent_section=None, source_type="rulebook", similarity=0.9,
)


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture
def metered_client(request):
    """TestClient with metering settings + fake redis, pipeline mocked.

    Parametrize indirectly with a dict: {"enabled": bool, "redis": _FakeRedis}.
    """
    param = getattr(request, "param", {}) or {}
    fake_redis = param.get("redis", _FakeRedis())

    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.main import app

    _reset_limiter()

    settings = _fake_settings()
    settings.metering_enabled = param.get("enabled", False)

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.Client", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=settings),
        patch("app.usage.get_redis", return_value=fake_redis),
        # A real chunk so generation runs and produces usage (an empty context
        # short-circuits with usage=None); reranker stubbed so no model loads.
        patch("app.rag.pipeline.hybrid_search", return_value=[_CHUNK]),
        patch("app.rag.pipeline.rerank", side_effect=lambda q, c, **kw: c),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        with TestClient(app) as c:
            c.fake_redis = fake_redis
            yield c

    app.dependency_overrides.clear()


_QUERY = {"question": "What happens when both players do nothing?"}
# The TestClient's remote addr — no proxy secret in tests, so identity falls
# back to ip:{addr} exactly like an unproxied request in prod.
_TESTCLIENT_ID = "ip:testclient"


def _exhausted_redis(personal=None, global_=None):
    values = {}
    if personal is not None:
        values[user_key(_TESTCLIENT_ID, _now())] = str(personal)
    if global_ is not None:
        values[global_key(_now())] = str(global_)
    return _FakeRedis(values=values)


# ---------------------------------------------------------------------------
# Flag OFF (default): nothing blocks, usage is still recorded
# ---------------------------------------------------------------------------


def test_flag_off_over_quota_still_answers(metered_client):
    metered_client.fake_redis.values[user_key(_TESTCLIENT_ID, _now())] = "999999999"

    resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 200


def test_flag_off_records_dark_counters(metered_client):
    resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 200
    incremented = {key for key, _ in metered_client.fake_redis.incrs}
    assert user_key(_TESTCLIENT_ID, _now()) in incremented
    assert global_key(_now()) in incremented


def test_health_reports_metering_disabled(metered_client):
    body = metered_client.get("/health").json()

    assert body["metering"] == {"enabled": False}


# ---------------------------------------------------------------------------
# Flag ON: the gate closes, distinguishable by cause, clean status pre-stream
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metered_client", [{"enabled": True, "redis": _exhausted_redis(personal=20_000)}], indirect=True,
)
def test_flag_on_personal_quota_429_with_login_hint(metered_client):
    resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 429
    assert "sign in" in resp.json()["detail"].lower()
    assert int(resp.headers["Retry-After"]) > 0


@pytest.mark.parametrize(
    "metered_client", [{"enabled": True, "redis": _exhausted_redis(global_=500_000)}], indirect=True,
)
def test_flag_on_global_budget_429_is_distinguishable(metered_client):
    resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 429
    assert "budget" in resp.json()["detail"].lower()


@pytest.mark.parametrize(
    "metered_client", [{"enabled": True, "redis": _exhausted_redis(personal=20_000)}], indirect=True,
)
def test_flag_on_stream_429s_with_clean_status_before_streaming(metered_client):
    resp = metered_client.post("/api/v1/query/stream", json=_QUERY)

    assert resp.status_code == 429
    assert "text/event-stream" not in resp.headers.get("content-type", "")


@pytest.mark.parametrize(
    "metered_client", [{"enabled": True, "redis": _FakeRedis(fail=True)}], indirect=True,
)
def test_flag_on_redis_down_fails_open(metered_client):
    resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 200


@pytest.mark.parametrize("metered_client", [{"enabled": True}], indirect=True)
def test_flag_on_under_quota_passes_and_health_reports_enabled(metered_client):
    resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 200
    assert metered_client.get("/health").json()["metering"] == {"enabled": True}


# ---------------------------------------------------------------------------
# Post-response bookkeeping goes through record_query_usage (both endpoints)
# ---------------------------------------------------------------------------


def test_query_records_usage_after_response(metered_client):
    with patch("app.api.v1.query.record_query_usage") as mock_record:
        resp = metered_client.post("/api/v1/query", json=_QUERY)

    assert resp.status_code == 200
    mock_record.assert_called_once()
    identity = mock_record.call_args.args[1]
    assert identity.user_id == _TESTCLIENT_ID


def test_stream_records_usage_on_final_event(metered_client):
    with patch("app.api.v1.query.record_query_usage") as mock_record:
        resp = metered_client.post("/api/v1/query/stream", json=_QUERY)

    assert resp.status_code == 200
    assert "event: final" in resp.text
    mock_record.assert_called_once()


# ---------------------------------------------------------------------------
# GET /api/v1/usage — works with the flag off
# ---------------------------------------------------------------------------


def test_usage_endpoint_reports_counters_flag_off(metered_client):
    metered_client.fake_redis.values[user_key(_TESTCLIENT_ID, _now())] = "1500"

    body = metered_client.get("/api/v1/usage").json()

    assert body["used"] == 1500
    assert body["quota"] == 20_000
    assert body["remaining"] == 18_500
    assert body["tier"] == "anon"
    assert body["resets_at"]  # ISO string of next midnight UTC


def test_usage_endpoint_fails_open_to_zero_used(metered_client):
    metered_client.fake_redis.fail = True

    body = metered_client.get("/api/v1/usage").json()

    assert body["used"] == 0
    assert body["remaining"] == body["quota"]
