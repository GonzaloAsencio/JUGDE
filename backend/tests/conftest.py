"""Test fixtures and fake collaborators for the RAG pipeline."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.rag.generation import GenerationTimeout
from app.rag.schemas import Citation, QueryResponse


class FakeEmbedder:
    def encode(self, text: str) -> list[float]:
        return [0.0] * 1024


class FakePool:
    """Stub DB pool — vector_search is mocked at the function level in tests."""
    pass


class FakeGeminiClient:
    def generate_content(self, prompt, generation_config=None, request_options=None):
        class _Response:
            text = "Fake answer for testing."
        return _Response()


class FakeGeminiTimeout:
    def generate_content(self, prompt, generation_config=None, request_options=None):
        raise GenerationTimeout("timeout")


def _make_client(gemini_override=None):
    """Build a TestClient with all heavy startup steps mocked out."""
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_client
    from app.main import app

    gemini = gemini_override if gemini_override is not None else FakeGeminiClient()

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_client] = lambda: gemini

    # Patch lifespan-level heavy operations so TestClient startup doesn't fail
    patches = [
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch(
            "app.main.genai.configure",
        ),
        patch(
            "app.main.genai.GenerativeModel",
            return_value=gemini,
        ),
        # Patch corpus_version resolution: mock get_conn so the MAX query returns "v1"
        patch(
            "app.main.get_conn",
        ),
        # Patch settings so corpus_version is already set (skips MAX query)
        patch(
            "app.main.get_settings",
            return_value=_fake_settings(),
        ),
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
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_client
    from app.main import app

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_client] = lambda: FakeGeminiClient()

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=FakeGeminiClient()),
        patch("app.main.get_settings", return_value=_fake_settings()),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def timeout_client():
    """Client whose Gemini dependency raises GenerationTimeout."""
    from app.api.v1.query import get_db_pool, get_embedder, get_llm_client
    from app.main import app

    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    app.dependency_overrides[get_db_pool] = lambda: FakePool()
    app.dependency_overrides[get_llm_client] = lambda: FakeGeminiTimeout()

    with (
        patch("app.main.init_pool", return_value=MagicMock()),
        patch("app.main.close_pool"),
        patch("app.main.Embedder.load", return_value=FakeEmbedder()),
        patch("app.main.genai.configure"),
        patch("app.main.genai.GenerativeModel", return_value=FakeGeminiClient()),
        patch("app.main.get_settings", return_value=_fake_settings()),
    ):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()
