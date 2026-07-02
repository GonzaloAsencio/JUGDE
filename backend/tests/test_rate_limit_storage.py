"""Rate-limit storage backend resolution.

In-memory counters are per-process and useless across replicas, so production
with >1 worker must point RATE_LIMIT_STORAGE_URI at a shared Redis. These tests
pin the resolution logic (env var -> shared store, absent -> in-memory).
"""
from app.middleware.rate_limit import _resolve_storage_uri


def test_defaults_to_in_memory_when_unset(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_STORAGE_URI", raising=False)
    assert _resolve_storage_uri() == "memory://"


def test_blank_env_var_falls_back_to_in_memory(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "   ")
    assert _resolve_storage_uri() == "memory://"


def test_uses_configured_redis_uri(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "redis://cache:6379")
    assert _resolve_storage_uri() == "redis://cache:6379"
