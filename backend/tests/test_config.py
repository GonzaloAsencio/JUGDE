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


def test_gemini_model_default_is_not_retired(monkeypatch):
    """Google retired the free tier for gemini-2.0-flash (429 with limit: 0 on
    every metric) and gemini-2.5-* is closed to new users — either default
    would make every Gemini-provider deploy without an explicit GEMINI_MODEL
    fail 100% of requests. The default must be a -latest alias so it tracks
    the models the free tier actually serves."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.gemini_model == "gemini-flash-lite-latest"


def test_enable_reranker_false_by_default(monkeypatch):
    # No longer a no-op as of PR2 — the pipeline now gates reranking on this
    # flag (pipeline.py _retrieve). Default stays False until eval confirms
    # the lift; this test only pins the default value.
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("ENABLE_RERANKER", "false")
    from app.config import Settings
    s = Settings()
    assert s.enable_reranker is False


def test_reranker_settings_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    for var in ("ENABLE_RERANKER", "RERANKER_MODEL", "RERANK_POOL_SIZE"):
        monkeypatch.delenv(var, raising=False)
    from app.config import Settings
    # _env_file=None: el .env local del dev no debe pisar los defaults bajo test
    s = Settings(_env_file=None)
    assert s.enable_reranker is False
    assert s.reranker_model == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert s.rerank_pool_size == 15


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
