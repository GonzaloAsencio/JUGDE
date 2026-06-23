"""Unit tests for the LLM rate-limit retry helper.

A single shared LLM endpoint serves HyDE, generation, and the eval judge. Under
load (e.g. free-tier quota), 429s appear and previously either errored the
pipeline or silently degraded HyDE to raw-only. _completion_with_retry retries
429s with exponential backoff so a transient throttle doesn't corrupt results.
"""
import pytest

from app.rag.generation import _completion_with_retry, _is_rate_limit


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


def test_backoff_is_exponential():
    delays = []

    def call():
        raise _FakeRateLimit("429")

    with pytest.raises(_FakeRateLimit):
        _completion_with_retry(call, max_retries=3, base_delay=1.0, sleep=delays.append)

    assert delays == [1.0, 2.0, 4.0]


def test_is_rate_limit_detects_429_status():
    assert _is_rate_limit(_FakeRateLimit("x")) is True
    assert _is_rate_limit(_FakeServerError("x")) is False
    assert _is_rate_limit(ValueError("nope")) is False
