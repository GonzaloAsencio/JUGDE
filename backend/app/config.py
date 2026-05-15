from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: str
    top_k: int = 5
    model_name: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    corpus_version: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    gemini_temperature: float = 0.1
    gemini_timeout_s: float = 30.0
    top_k_fetch: int = 15
    rrf_k: int = 60
    enable_reranker: bool = False

    # Runtime environment
    app_env: str = "development"

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

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
