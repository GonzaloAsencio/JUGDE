"""Test fixtures and fake collaborators for the RAG pipeline."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.rag.generation import GenerationTimeout
from app.rag.provider import LLMProvider
from app.rag.retrieval import Chunk
from app.rag.schemas import Citation, QueryResponse


class FakeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.0] * 1024


class FakePool:
    """Stub DB pool — vector_search is mocked at the function level in tests."""
    pass


class FakeLLMProvider(LLMProvider):
    def generate(self, question: str, chunks: list[Chunk]) -> str:
        return "Fake answer for testing."


class FakeLLMProviderTimeout(LLMProvider):
    def generate(self, question: str, chunks: list[Chunk]) -> str:
        raise GenerationTimeout("timeout")


# Keep aliases for test files that import these directly
FakeGeminiClient = FakeLLMProvider
FakeGeminiTimeout = FakeLLMProviderTimeout


def _make_client(provider_override=None):
    """Build a TestClient with all heavy startup steps mocked out."""
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.main import app

    provider = provider_override if provider_override is not None else FakeLLMProvider()

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_provider] = lambda: provider

    patches = [
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=MagicMock()),
        patch("app.main.get_conn"),
        patch("app.main.get_settings", return_value=_fake_settings()),
    ]

    for p in patches:
        p.start()

    client = TestClient(app, raise_server_exceptions=True)
    client.__enter__()

    return client, patches, app


def _fake_settings():
    """Return a minimal Settings-like object for tests."""
    from app.config import Settings
    import os

    # Provide required fields so Settings() doesn't fail validation
    os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    os.environ.setdefault("GEMINI_API_KEY", "fake-api-key")

    settings = Settings(
        database_url="postgresql://fake:fake@localhost/fake",
        gemini_api_key="fake-api-key",
        corpus_version="v1",  # pre-resolved, no MAX query needed
    )
    return settings


@pytest.fixture
def client():
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.main import app

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProvider()

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=_fake_settings()),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def timeout_client():
    """Client whose LLM provider raises GenerationTimeout."""
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_provider
    from app.main import app

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_provider] = lambda: FakeLLMProviderTimeout()

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=MagicMock()),
        patch("app.main.get_settings", return_value=_fake_settings()),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
