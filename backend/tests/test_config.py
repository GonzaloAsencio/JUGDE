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
    assert s.enable_reranker is True


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


def test_enable_reranker_true_by_default(monkeypatch):
    # The 2026-07-10 eval gate confirmed the lift the flag was waiting for:
    # deterministic recall went 9/15 -> 12/15 (60% -> 80%) with zero losses
    # (eval_results_20260710T155034Z.json vs 153424Z). Default is now True.
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("ENABLE_RERANKER", raising=False)
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.enable_reranker is True


def test_enable_reranker_env_override_false(monkeypatch):
    # Memory-constrained deploys (HF Space free tier) must still be able to
    # opt out of the ~80MB cross-encoder via env.
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
    assert s.enable_reranker is True
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


# ---------------------------------------------------------------------------
# Half-applied provider switch: reported, never fatal
#
# Swapping the main provider by rate limit means moving FOUR knobs
# (llm_provider, llm_model, llm_base_url, llm_api_key). Leaving three set while
# llm_provider lags is not a broken config — it is how you keep both sides ready
# and flip in one edit. Raising would force commenting out three vars on every
# 429, so this reports instead: stray_openai_compat_fields() feeds a startup
# WARNING (main.py), and /health plus LLMProvider.model make the live model
# observable. The bug was never the stray fields; it was that nothing said which
# model was answering, which on 2026-07-17 cost a wrong reading of a gate.
# ---------------------------------------------------------------------------

def test_stray_openai_compat_fields_are_reported_under_gemini():
    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake",
        gemini_api_key="fake-key",
        llm_provider="gemini",
        llm_model="gpt-oss-120b",
        llm_base_url="https://api.cerebras.ai/v1",
        llm_api_key="csk-fake",
    )
    assert s.stray_openai_compat_fields() == ["llm_base_url", "llm_api_key", "llm_model"]


def test_half_switched_config_still_boots():
    """The exact .env that fooled the 3.11.1a gate must still start: an operator
    mid-swap gets a warning, not a locked door."""
    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake",
        gemini_api_key="fake-key",
        llm_provider="gemini",
        llm_model="gpt-oss-120b",
        llm_base_url="https://api.cerebras.ai/v1",
        llm_api_key="csk-fake",
    )
    assert s.llm_provider == "gemini"


def test_no_stray_fields_when_openai_compat_is_the_active_provider():
    """Nothing is inert when the provider actually uses these — no warning."""
    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake",
        gemini_api_key="fake-key",
        llm_provider="openai_compat",
        llm_model="gpt-oss-120b",
        llm_base_url="https://api.cerebras.ai/v1",
        llm_api_key="csk-fake",
    )
    assert s.stray_openai_compat_fields() == []


def test_no_stray_fields_when_gemini_is_configured_alone(monkeypatch):
    # _env_file=None blocks the .env FILE, not the environment: scripts/eval.py
    # calls load_dotenv() at import time, so any test that imports it leaks the
    # developer's .env into os.environ for the rest of the session. Clear the
    # knobs explicitly or this asserts against whoever ran first.
    for var in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)

    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake",
        gemini_api_key="fake-key",
        llm_provider="gemini",
    )
    assert s.stray_openai_compat_fields() == []


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
