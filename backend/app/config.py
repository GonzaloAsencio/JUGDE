from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: str
    top_k: int = 5
    model_name: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    corpus_version: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = 0.1
    gemini_timeout_s: float = 10.0

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
