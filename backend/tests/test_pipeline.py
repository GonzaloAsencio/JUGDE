"""Unit tests for RAG pipeline: build_prompt, schemas, and answer_question."""
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.rag.generation import GenerationTimeout, build_prompt  # noqa: F401
from app.rag.retrieval import Chunk
from app.rag.schemas import Citation, QueryRequest, QueryResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chunk(
    section: str = "Test Section",
    content: str = "Some content about the rules.",
    source_type: str = "rulebook",
    similarity: float = 0.9,
) -> Chunk:
    return Chunk(
        id="abc123",
        content=content,
        section=section,
        parent_section=None,
        source_type=source_type,
        similarity=similarity,
    )


def _fake_settings(corpus_version: str = "v1"):
    """Minimal settings stub for pipeline tests."""
    s = MagicMock()
    s.corpus_version = corpus_version
    s.top_k = 5
    s.top_k_fetch = 15
    s.rrf_k = 60
    s.gemini_temperature = 0.1
    s.gemini_timeout_s = 10.0
    return s


# ---------------------------------------------------------------------------
# build_prompt tests
# ---------------------------------------------------------------------------

def test_build_prompt_contains_question():
    question = "How does double-tap work?"
    prompt = build_prompt(question, [_make_chunk()])
    assert question in prompt


def test_build_prompt_numbers_chunks():
    chunks = [_make_chunk(section=f"Section {i}") for i in range(3)]
    prompt = build_prompt("Any question?", chunks)
    assert "[#1]" in prompt
    assert "[#2]" in prompt
    assert "[#3]" in prompt


def test_build_prompt_includes_section():
    chunk = _make_chunk(section="Deck Construction")
    prompt = build_prompt("What is deck construction?", [chunk])
    assert "Deck Construction" in prompt


def test_build_prompt_empty_chunks():
    """Empty chunk list must not crash and must still produce a valid prompt."""
    prompt = build_prompt("Can I ask with no context?", [])
    assert "=== PREGUNTA ===" in prompt
    assert "=== RESPUESTA ===" in prompt
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

def test_query_request_too_short():
    with pytest.raises(ValidationError):
        QueryRequest(question="ab")  # 2 chars, min_length=3


def test_query_request_too_long():
    with pytest.raises(ValidationError):
        QueryRequest(question="x" * 501)  # 501 chars, max_length=500


def test_query_response_schema():
    citation = Citation(
        section="Rules",
        source_type="rulebook",
        content_preview="Short preview.",
        similarity=0.85,
    )
    response = QueryResponse(answer="Answer text.", citations=[citation], latency_ms=42)
    assert response.answer == "Answer text."
    assert len(response.citations) == 1
    assert response.latency_ms == 42


# ---------------------------------------------------------------------------
# answer_question tests
# ---------------------------------------------------------------------------

async def test_pipeline_empty_chunks_returns_fallback():
    """When vector_search returns [], the answer is the fallback message and citations=[]."""
    from tests.conftest import FakeEmbedder

    fake_embedder = FakeEmbedder()
    fake_gemini = MagicMock()  # should NOT be called
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "What is a rule?", fake_embedder, MagicMock(), fake_gemini, settings
                )

    assert result.citations == []
    assert "No tengo información" in result.answer
    fake_gemini.generate_content.assert_not_called()


async def test_pipeline_latency_ms_populated():
    """latency_ms must be a non-negative integer in the response."""
    from tests.conftest import FakeEmbedder

    fake_embedder = FakeEmbedder()
    fake_gemini = MagicMock()
    fake_gemini.generate_content.return_value = MagicMock(text="An answer.")
    settings = _fake_settings()

    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.call_gemini", return_value="An answer."):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = await answer_question(
                        "How does it work?", fake_embedder, MagicMock(), fake_gemini, settings
                    )

    assert isinstance(result.latency_ms, int)
    assert result.latency_ms >= 0


async def test_pipeline_citation_preview_truncated_to_200_chars():
    """content_preview must be exactly content[:200] even when chunk.content exceeds 200 chars."""
    from tests.conftest import FakeEmbedder

    long_content = "r" * 500
    chunk = _make_chunk(content=long_content)
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.call_gemini", return_value="Answer."):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = await answer_question(
                        "Any question?", FakeEmbedder(), MagicMock(), MagicMock(), settings
                    )

    assert len(result.citations[0].content_preview) <= 200
    assert result.citations[0].content_preview == long_content[:200]


async def test_pipeline_propagates_generation_timeout():
    """answer_question must propagate GenerationTimeout without swallowing it."""
    from tests.conftest import FakeEmbedder

    chunk = _make_chunk()
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.call_gemini", side_effect=GenerationTimeout("timeout")):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    with pytest.raises(GenerationTimeout):
                        await answer_question(
                            "What is a rule?", FakeEmbedder(), MagicMock(), MagicMock(), settings
                        )
