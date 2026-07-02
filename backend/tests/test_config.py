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


# ---------------------------------------------------------------------------
# Fail-closed auth in production
# ---------------------------------------------------------------------------

def test_production_without_secret_refuses_to_start(monkeypatch):
    """app_env=production with no proxy_shared_secret must raise, not boot open."""
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url="postgresql://fake",
            gemini_api_key="fake-key",
            app_env="production",
            proxy_shared_secret=None,
        )


def test_production_with_secret_starts(monkeypatch):
    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake",
        gemini_api_key="fake-key",
        app_env="production",
        proxy_shared_secret="a-real-secret",
    )
    assert s.proxy_shared_secret == "a-real-secret"


def test_development_without_secret_is_allowed(monkeypatch):
    """Local dev must still boot without a secret (auth disabled)."""
    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake",
        gemini_api_key="fake-key",
        app_env="development",
        proxy_shared_secret=None,
    )
    assert s.proxy_shared_secret is None
