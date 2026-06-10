"""Unit tests for Settings defaults."""
import pytest


def test_settings_rrf_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    # Los scripts importados por otros tests hacen load_dotenv() y vuelcan el
    # .env local a os.environ — limpiamos las vars que este test asserta.
    for var in ("TOP_K_FETCH", "RRF_K", "ENABLE_RERANKER"):
        monkeypatch.delenv(var, raising=False)
    from app.config import Settings
    # _env_file=None: el .env local del dev no debe pisar los defaults bajo test
    s = Settings(_env_file=None)
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
