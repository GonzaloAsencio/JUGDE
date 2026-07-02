"""Unit tests for the LLM rate-limit retry helper.

A single shared LLM endpoint serves HyDE, generation, and the eval judge. Under
load (e.g. free-tier quota), 429s appear and previously either errored the
pipeline or silently degraded HyDE to raw-only. _completion_with_retry retries
429s with exponential backoff so a transient throttle doesn't corrupt results.
"""
import pytest

from app.rag.generation import (
    _RATE_LIMIT_MAX_DELAY,
    _RATE_LIMIT_MAX_RETRIES,
    _completion_with_retry,
    _is_rate_limit,
)


class _FakeRateLimit(Exception):
    """Stands in for openai.RateLimitError without its heavy constructor."""
    status_code = 429


class _FakeServerError(Exception):
    status_code = 500


def _no_sleep(_seconds):
    pass


def test_returns_first_success_without_retry():
    calls = []

    def call():
        calls.append(1)
        return "ok"

    assert _completion_with_retry(call, sleep=_no_sleep) == "ok"
    assert len(calls) == 1


def test_retries_on_rate_limit_then_succeeds():
    attempts = []

    def call():
        attempts.append(1)
        if len(attempts) < 3:
            raise _FakeRateLimit("429")
        return "recovered"

    assert _completion_with_retry(call, base_delay=0.01, sleep=_no_sleep) == "recovered"
    assert len(attempts) == 3


def test_raises_after_exhausting_retries():
    def call():
        raise _FakeRateLimit("429")

    with pytest.raises(_FakeRateLimit):
        _completion_with_retry(call, max_retries=2, base_delay=0.01, sleep=_no_sleep)


def test_does_not_retry_non_rate_limit_error():
    attempts = []

    def call():
        attempts.append(1)
        raise _FakeServerError("500")

    with pytest.raises(_FakeServerError):
        _completion_with_retry(call, sleep=_no_sleep)
    assert len(attempts) == 1, "a non-429 must fail fast, not waste retries"


def test_backoff_grows_exponentially_within_jitter():
    """Each delay sits in [base*2**i, base*2**i + jitter): exponential + jitter.

    Jitter (added to avoid a thundering herd of synchronized retries) breaks the
    old exact-equality assertion, so we bound each delay by its exponential floor
    and a small jitter ceiling instead.
    """
    delays = []

    def call():
        raise _FakeRateLimit("429")

    with pytest.raises(_FakeRateLimit):
        _completion_with_retry(call, max_retries=3, base_delay=1.0, sleep=delays.append)

    expected_floors = [1.0, 2.0, 4.0]
    assert len(delays) == 3
    for actual, floor in zip(delays, expected_floors):
        assert floor <= actual < floor + 1.0  # jitter budget < 1s


def test_backoff_is_capped_so_it_never_reaches_the_old_30s():
    """Delays are capped at _RATE_LIMIT_MAX_DELAY; total worst case stays small.

    The old schedule (4 retries, base 2.0, no cap) summed to 30s and, on a
    threadpool worker, tied it up that long. A large base must now be clamped.
    """
    delays = []

    def call():
        raise _FakeRateLimit("429")

    with pytest.raises(_FakeRateLimit):
        # base 10 would explode to 10,20,40 uncapped; the cap must clamp it.
        _completion_with_retry(call, base_delay=10.0, sleep=delays.append)

    assert len(delays) == _RATE_LIMIT_MAX_RETRIES
    assert all(d <= _RATE_LIMIT_MAX_DELAY + 1.0 for d in delays)  # + jitter budget
    assert sum(delays) < 15.0  # nowhere near the old 30s


def test_is_rate_limit_detects_429_status():
    assert _is_rate_limit(_FakeRateLimit("x")) is True
    assert _is_rate_limit(_FakeServerError("x")) is False
    assert _is_rate_limit(ValueError("nope")) is False
