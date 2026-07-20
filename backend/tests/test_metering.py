"""Metering core (Fase 5, PR2a) — identity, quotas, recording, ledger.

Contract under test:
- ``get_user_identity`` mirrors the rate_limit trust model: ``X-User-Id``
  (``anon:{uuid}`` | ``auth:{sub}``, prefix decides the tier) is honored ONLY
  behind a valid ``X-Proxy-Secret``; then ``X-Real-IP`` behind the same proof;
  last resort the remote address. A spoofed header must never mint a fresh
  quota bucket.
- ``check_quota`` reads BOTH ceilings (personal by tier, global daily budget)
  and reports which one blocked. ``record_usage`` does two INCRBY + EXPIRE.
- FAIL-OPEN everywhere: Redis down/missing/raising -> the query passes with a
  warning. Metering protects the free tier; it must never take the app down.
- ``enforce_quota`` gates ONLY when metering_enabled; 429s are distinguishable
  by cause and carry Retry-After to midnight UTC.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.usage import (
    Identity,
    check_quota,
    enforce_quota,
    get_user_identity,
    global_key,
    record_usage,
    seconds_to_reset,
    user_key,
)


def _settings(**overrides):
    base = dict(
        proxy_shared_secret=None,
        metering_enabled=False,
        anon_daily_token_quota=20_000,
        auth_daily_token_quota=100_000,
        global_daily_token_budget=500_000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _req(headers=None, client_host="9.9.9.9", settings=None):
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (client_host, 1234),
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings or _settings())),
    }
    return Request(scope)


class _FakeRedis:
    def __init__(self, values=None, fail=False):
        self.values = values or {}
        self.fail = fail
        self.incrs: list[tuple[str, int]] = []
        self.expires: list[tuple[str, int]] = []

    def get(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        return self.values.get(key)

    def incrby(self, key, amount):
        if self.fail:
            raise RuntimeError("redis down")
        self.incrs.append((key, amount))
        return amount

    def expire(self, key, ttl):
        self.expires.append((key, ttl))
        return True


_NOW = datetime(2026, 7, 19, 15, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Identity: the trusted-proxy contract
# ---------------------------------------------------------------------------


def test_identity_falls_back_to_remote_addr_without_secret():
    request = _req(headers={"X-User-Id": "anon:evil"}, settings=_settings())

    assert get_user_identity(request) == Identity(user_id="ip:9.9.9.9", tier="anon")


def test_identity_ignores_user_id_with_wrong_secret():
    settings = _settings(proxy_shared_secret="s3cret")
    request = _req(
        headers={"X-Proxy-Secret": "WRONG", "X-User-Id": "anon:abc"}, settings=settings,
    )

    assert get_user_identity(request) == Identity(user_id="ip:9.9.9.9", tier="anon")


def test_identity_honors_anon_user_id_behind_valid_secret():
    settings = _settings(proxy_shared_secret="s3cret")
    request = _req(
        headers={"X-Proxy-Secret": "s3cret", "X-User-Id": "anon:abc-123"}, settings=settings,
    )

    assert get_user_identity(request) == Identity(user_id="anon:abc-123", tier="anon")


def test_identity_auth_prefix_decides_the_tier():
    settings = _settings(proxy_shared_secret="s3cret")
    request = _req(
        headers={"X-Proxy-Secret": "s3cret", "X-User-Id": "auth:sub-42"}, settings=settings,
    )

    assert get_user_identity(request) == Identity(user_id="auth:sub-42", tier="auth")


def test_identity_rejects_malformed_or_oversized_user_id():
    settings = _settings(proxy_shared_secret="s3cret")
    for bad in ["other:abc", "anon:", "auth:" + "x" * 300]:
        request = _req(
            headers={"X-Proxy-Secret": "s3cret", "X-User-Id": bad, "X-Real-IP": "1.2.3.4"},
            settings=settings,
        )

        assert get_user_identity(request) == Identity(user_id="ip:1.2.3.4", tier="anon")


def test_identity_uses_real_ip_behind_secret_when_no_user_id():
    settings = _settings(proxy_shared_secret="s3cret")
    request = _req(
        headers={"X-Proxy-Secret": "s3cret", "X-Real-IP": "1.2.3.4"}, settings=settings,
    )

    assert get_user_identity(request) == Identity(user_id="ip:1.2.3.4", tier="anon")


# ---------------------------------------------------------------------------
# Quota check: two ceilings, distinguishable
# ---------------------------------------------------------------------------


def _check(identity, values, settings=None, fail=False):
    fake = _FakeRedis(values=values, fail=fail)
    with patch("app.usage.get_redis", return_value=fake):
        with patch("app.usage._utc_now", return_value=_NOW):
            return check_quota(identity, settings or _settings())


def test_check_quota_allows_under_both_ceilings():
    identity = Identity("anon:u1", "anon")
    status = _check(identity, {user_key("anon:u1", _NOW): "100", global_key(_NOW): "1000"})

    assert status.allowed is True
    assert status.reason is None
    assert status.used == 100
    assert status.quota == 20_000


def test_check_quota_blocks_on_personal_limit():
    identity = Identity("anon:u1", "anon")
    status = _check(identity, {user_key("anon:u1", _NOW): "20000"})

    assert status.allowed is False
    assert status.reason == "personal"


def test_check_quota_auth_tier_uses_the_higher_quota():
    identity = Identity("auth:u2", "auth")
    status = _check(identity, {user_key("auth:u2", _NOW): "50000"})

    assert status.allowed is True
    assert status.quota == 100_000


def test_check_quota_blocks_on_global_budget():
    identity = Identity("anon:u1", "anon")
    status = _check(identity, {global_key(_NOW): "500000"})

    assert status.allowed is False
    assert status.reason == "global"


def test_check_quota_fails_open_when_redis_raises():
    status = _check(Identity("anon:u1", "anon"), {}, fail=True)

    assert status.allowed is True


def test_check_quota_fails_open_without_redis():
    with patch("app.usage.get_redis", return_value=None):
        status = check_quota(Identity("anon:u1", "anon"), _settings())

    assert status.allowed is True


# ---------------------------------------------------------------------------
# Recording: two INCRBY + EXPIRE, fail-open
# ---------------------------------------------------------------------------


def test_record_usage_increments_personal_and_global_with_ttl():
    fake = _FakeRedis()
    with patch("app.usage.get_redis", return_value=fake):
        with patch("app.usage._utc_now", return_value=_NOW):
            record_usage(Identity("anon:u1", "anon"), 120)

    assert (user_key("anon:u1", _NOW), 120) in fake.incrs
    assert (global_key(_NOW), 120) in fake.incrs
    assert len(fake.expires) == 2
    for _, ttl in fake.expires:
        assert 0 < ttl <= 86400 + 3600, "TTL must be bounded by a day plus the margin"


def test_record_usage_skips_zero_tokens():
    fake = _FakeRedis()
    with patch("app.usage.get_redis", return_value=fake):
        record_usage(Identity("anon:u1", "anon"), 0)

    assert fake.incrs == []


def test_record_usage_swallows_redis_errors():
    fake = _FakeRedis(fail=True)
    with patch("app.usage.get_redis", return_value=fake):
        record_usage(Identity("anon:u1", "anon"), 120)  # must not raise


# ---------------------------------------------------------------------------
# enforce_quota: the gate — flag off never 429s
# ---------------------------------------------------------------------------


def _enforce(values, *, settings, headers=None):
    fake = _FakeRedis(values=values)
    request = _req(headers=headers, settings=settings)
    with patch("app.usage.get_redis", return_value=fake):
        with patch("app.usage._utc_now", return_value=_NOW):
            return enforce_quota(request)


def test_enforce_quota_flag_off_never_blocks():
    settings = _settings(metering_enabled=False)
    identity = _enforce({user_key("ip:9.9.9.9", _NOW): "999999999"}, settings=settings)

    assert identity == Identity("ip:9.9.9.9", "anon")


def test_enforce_quota_personal_429_tells_anon_to_sign_in():
    settings = _settings(metering_enabled=True)
    with pytest.raises(HTTPException) as exc:
        _enforce({user_key("ip:9.9.9.9", _NOW): "20000"}, settings=settings)

    assert exc.value.status_code == 429
    assert "sign in" in exc.value.detail.lower()
    assert int(exc.value.headers["Retry-After"]) > 0


def test_enforce_quota_global_429_is_distinguishable():
    settings = _settings(metering_enabled=True)
    with pytest.raises(HTTPException) as exc:
        _enforce({global_key(_NOW): "500000"}, settings=settings)

    assert exc.value.status_code == 429
    assert "budget" in exc.value.detail.lower()
    assert "sign in" not in exc.value.detail.lower()


def test_enforce_quota_flag_on_under_quota_passes():
    settings = _settings(metering_enabled=True)
    identity = _enforce({}, settings=settings)

    assert identity.tier == "anon"


# ---------------------------------------------------------------------------
# Reset clock
# ---------------------------------------------------------------------------


def test_seconds_to_reset_counts_down_to_midnight_utc():
    with patch("app.usage._utc_now", return_value=_NOW):
        assert seconds_to_reset() == 9 * 3600  # 15:00 UTC -> 24:00 UTC


# ---------------------------------------------------------------------------
# Ledger + post-response bookkeeping
# ---------------------------------------------------------------------------


class _CapturingCursor:
    def __init__(self, log):
        self._log = log

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params):
        self._log.append((sql, params))


class _CapturingConn:
    def __init__(self, log):
        self._log = log
        self.committed = False

    def cursor(self):
        return _CapturingCursor(self._log)

    def commit(self):
        self.committed = True


def _fake_response(usage=None, cache_hit=False):
    return SimpleNamespace(usage=usage, cache_hit=cache_hit)


def _run_ledger(identity, response):
    from app.usage import record_ledger
    from contextlib import contextmanager

    executed: list = []
    conn = _CapturingConn(executed)

    @contextmanager
    def _fake_get_conn(pool):
        yield conn

    with patch("app.db.get_conn", _fake_get_conn):
        record_ledger(object(), identity, response)
    return executed, conn


def test_record_ledger_writes_opaque_id_and_counts_only():
    from app.rag.schemas import Usage

    usage = Usage(prompt_tokens=100, output_tokens=20, total_tokens=120, llm_model="m-1")
    executed, conn = _run_ledger(Identity("anon:u1", "anon"), _fake_response(usage=usage))

    assert conn.committed is True
    (sql, params), = executed
    assert params == ("anon:u1", "m-1", 100, 20, 120, False, False)


def test_record_ledger_cache_hit_row_has_zero_tokens_and_cached_true():
    executed, _ = _run_ledger(Identity("anon:u1", "anon"), _fake_response(usage=None, cache_hit=True))

    (_, params), = executed
    assert params == ("anon:u1", None, 0, 0, 0, False, True)


def test_record_ledger_swallows_db_errors():
    from app.usage import record_ledger

    with patch("app.db.get_conn", side_effect=RuntimeError("db down")):
        record_ledger(object(), Identity("anon:u1", "anon"), _fake_response())  # must not raise


def test_record_query_usage_skips_redis_for_cache_hits():
    from app.usage import record_query_usage

    fake = _FakeRedis()
    with patch("app.usage.get_redis", return_value=fake):
        with patch("app.usage.record_ledger") as mock_ledger:
            record_query_usage(object(), Identity("anon:u1", "anon"), _fake_response(usage=None, cache_hit=True))

    assert fake.incrs == [], "a cache hit spent nothing — counters must not move"
    mock_ledger.assert_called_once()


def test_finalized_usage_names_the_answering_model():
    from tests.test_usage_capture import _MeteredProvider, _ask

    response, _ = _ask(_MeteredProvider())

    assert response.usage.llm_model == "fake-model"


# ---------------------------------------------------------------------------
# Ledger migration: auditability without PII
# ---------------------------------------------------------------------------


def test_usage_ledger_migration_has_no_question_text_column():
    import pathlib

    sql = (pathlib.Path(__file__).parent.parent / "migrations" / "009_usage_ledger.sql").read_text(
        encoding="utf-8"
    )
    create = sql.lower().split("create table")[1]
    assert "usage_ledger" in create
    for pii in ("question", "email", "answer"):
        assert pii not in create, f"ledger must not store {pii} (zero-PII contract, plan 5.1)"
