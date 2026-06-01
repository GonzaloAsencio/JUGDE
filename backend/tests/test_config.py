"""Unit tests for Settings defaults."""
import pytest


def test_settings_rrf_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    from app.config import Settings
    s = Settings()
    assert s.top_k_fetch == 15
    assert s.rrf_k == 60
    assert s.enable_reranker is False


def test_enable_reranker_false_is_noop(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("ENABLE_RERANKER", "false")
    from app.config import Settings
    s = Settings()
    assert s.enable_reranker is False


def test_corpus_version_strips_whitespace(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("CORPUS_VERSION", "v2.0.0  ")
    from app.config import Settings
    s = Settings()
    assert s.corpus_version == "v2.0.0"
