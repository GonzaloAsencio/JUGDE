from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: str | None = None
    top_k: int = 5
    model_name: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    corpus_version: str | None = None
    # -latest alias on purpose: Google retired the gemini-2.0-flash free tier
    # (limit: 0) and closed gemini-2.5-* to new users; a pinned retired model
    # here means every request 429s until someone notices.
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_temperature: float = 0.1
    gemini_timeout_s: float = 30.0
    # Ceiling for the answer-generation call, the only LLM call that had no
    # output cap (HyDE: 160, rewrite: 120). Output tokens are the expensive
    # side. If answers start truncating, the existing gemini.max_tokens warning
    # fires — raise this instead of removing it. Applies to both providers.
    max_output_tokens: int = 1024
    top_k_fetch: int = 15
    rrf_k: int = 60
    # Flipped to True after the 2026-07-10 eval gate: deterministic recall
    # 9/15 -> 12/15 (60% -> 80%) with zero losses, at zero LLM tokens (local
    # CPU cross-encoder, ~80MB RAM). Opt out per-deploy via ENABLE_RERANKER.
    enable_reranker: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_pool_size: int = 15

    # LLM provider: "gemini" (default) | "openai_compat" (Groq, LM Studio, Ollama, etc.)
    llm_provider: str = "gemini"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    @field_validator("corpus_version", mode="after")
    @classmethod
    def _strip_corpus_version(cls, v: str | None) -> str | None:
        # Espacios accidentales en la env var rompen el match exacto
        # WHERE corpus_version = %s contra la DB. Normalizamos siempre.
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check_provider_fields(self):
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError("gemini_api_key is required when llm_provider=gemini")
        if self.llm_provider == "openai_compat":
            missing = [name for name, val in [
                ("llm_base_url", self.llm_base_url),
                ("llm_api_key", self.llm_api_key),
                ("llm_model", self.llm_model),
            ] if not val]
            if missing:
                raise ValueError(f"openai_compat requires: {missing}")
        return self

    @model_validator(mode="after")
    def _require_secret_in_prod(self):
        # Fail-closed: the auth middleware disables itself when
        # proxy_shared_secret is None. In production that would silently expose
        # the whole backend (and burn the LLM quota) on a misconfigured deploy.
        # Refuse to start instead of booting "healthy" but wide open.
        if self.app_env == "production" and not self.proxy_shared_secret:
            raise ValueError(
                "proxy_shared_secret is required when app_env=production (fail-closed auth)"
            )
        return self

    # Runtime environment
    app_env: str = "development"

    # Shared secret between the Next.js proxy and this backend.
    # When set, every endpoint except shallow /health requires the
    # X-Proxy-Secret header. When None, auth is disabled (local dev).
    proxy_shared_secret: str | None = None

    # Upstash Redis (optional — cache disabled if not set)
    upstash_redis_url: str | None = None
    upstash_redis_token: str | None = None

    # Langfuse (optional — tracing disabled if not set)
    langfuse_secret_key: str | None = None
    langfuse_public_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Sentry (optional — error reporting disabled if not set)
    sentry_dsn: str | None = None
    sentry_sample_rate: float = 0.1

    # Rate limiting
    rate_limit_enabled: bool = True
    rate_limit_per_min: int = 10
    rate_limit_per_day: int = 100

    # Cache
    cache_ttl_s: int = 86400
    # v6: few-shot chaining examples in the system prompt (improvement plan 4.1).
    # Bumping invalidates the response cache — the version is part of the key.
    prompt_version: str = "v6"

    # DB connection pool sizing. maxconn must not exceed the database's
    # max_connections; a worker that finds the pool exhausted gets a fast 503
    # (see the query handler) instead of blocking.
    db_pool_min: int = 1
    db_pool_max: int = 10

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
