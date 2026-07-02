"""TDD: Citation expone el set de la expansión, propagado desde chunk.metadata."""
from unittest.mock import MagicMock, patch

import pytest

from app.rag.retrieval import Chunk
from app.rag.schemas import Citation


def _make_chunk(metadata=None) -> Chunk:
    return Chunk(
        id="abc123",
        content="Some content about the rules.",
        section="Test Section",
        parent_section=None,
        source_type="rulebook",
        similarity=0.9,
        metadata=metadata,
    )


def _fake_settings():
    s = MagicMock()
    s.corpus_version = "v1"
    s.top_k = 5
    s.top_k_fetch = 15
    s.rrf_k = 60
    s.gemini_temperature = 0.1
    s.gemini_timeout_s = 10.0
    s.prompt_version = "v5"
    s.cache_ttl_s = 86400
    return s


def test_citation_set_defaults_to_none():
    c = Citation(
        section="S", source_type="rulebook", content_preview="x", similarity=1.0
    )
    assert c.set is None


def test_citation_accepts_set():
    c = Citation(
        section="S", source_type="errata", content_preview="x", similarity=1.0, set="origins"
    )
    assert c.set == "origins"


@pytest.mark.asyncio
async def test_pipeline_propagates_set_from_metadata():
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    chunk = _make_chunk(metadata={"set": "spiritforged"})
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = answer_question(
                    "Any question?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert result.citations[0].set == "spiritforged"


@pytest.mark.asyncio
async def test_pipeline_set_none_when_no_metadata():
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    chunk = _make_chunk(metadata=None)
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = answer_question(
                    "Any question?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert result.citations[0].set is None
