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
    s.prompt_version = "v5"
    s.cache_ttl_s = 86400
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
    assert "=== QUESTION ===" in prompt
    assert "=== RESPONSE" in prompt
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
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "What is a rule?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert result.citations == []
    assert "I don't have enough information" in result.answer


async def test_pipeline_latency_ms_populated():
    """latency_ms must be a non-negative integer in the response."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    settings = _fake_settings()

    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "How does it work?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert isinstance(result.latency_ms, int)
    assert result.latency_ms >= 0


async def test_pipeline_citation_preview_truncated_to_200_chars():
    """content_preview must be exactly content[:200] even when chunk.content exceeds 200 chars."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    long_content = "r" * 500
    chunk = _make_chunk(content=long_content)
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "Any question?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert len(result.citations[0].content_preview) <= 200
    assert result.citations[0].content_preview == long_content[:200]


async def test_pipeline_propagates_generation_timeout():
    """answer_question must propagate GenerationTimeout without swallowing it."""
    from tests.conftest import FakeEmbedder, FakeLLMProviderTimeout

    chunk = _make_chunk()
    settings = _fake_settings()

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                with pytest.raises(GenerationTimeout):
                    await answer_question(
                        "What is a rule?", FakeEmbedder(), MagicMock(), FakeLLMProviderTimeout(), settings
                    )


# ---------------------------------------------------------------------------
# Query transform: fuse_eq (raw + HyDE). Production winner from the offline
# experiment (recall@5 41%->59%). Arm A embeds the RAW question; arm B embeds a
# HyDE passage; the two hybrid_search result lists are RRF-fused. When the
# provider yields no HyDE (base providers), the pipeline degrades to raw-only.
# ---------------------------------------------------------------------------

from tests.conftest import FakeLLMProvider


class _HydeProvider(FakeLLMProvider):
    """Provider that supplies a HyDE passage, enabling the two-arm fusion path."""
    def hyde(self, question: str) -> str:
        return "A hypothetical confident answer using official terminology."


async def test_pipeline_fuses_raw_and_hyde_when_provider_supplies_hyde():
    """When provider.hyde() returns text, the pipeline retrieves TWICE (raw + HyDE)
    and fuses both arms into the citations."""
    from tests.conftest import FakeEmbedder

    raw_chunk = _make_chunk(section="RAW")
    hyde_chunk = _make_chunk(section="HYDE")
    object.__setattr__(raw_chunk, "id", "raw_id")
    object.__setattr__(hyde_chunk, "id", "hyde_id")

    calls: list[str] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        calls.append(text)
        return [raw_chunk] if len(calls) == 1 else [hyde_chunk]

    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "How many cards are in a starting deck?",
                    FakeEmbedder(), MagicMock(), _HydeProvider(), _fake_settings(),
                )

    assert len(calls) == 2, "expected one retrieval per arm (raw + HyDE)"
    sections = {c.section for c in result.citations}
    assert sections == {"RAW", "HYDE"}, "both arms must contribute to the fused result"


async def test_pipeline_arm_a_embeds_raw_question_not_rewrite():
    """Arm A must retrieve on the RAW question text — Option A drops rewrite_query
    from the embedding path."""
    from tests.conftest import FakeEmbedder

    calls: list[str] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        calls.append(text)
        return [_make_chunk()]

    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                await answer_question(
                    "What is a unit?",
                    FakeEmbedder(), MagicMock(), _HydeProvider(), _fake_settings(),
                )

    assert calls[0] == "What is a unit?", "arm A must use the raw question verbatim"


async def test_pipeline_degrades_to_raw_only_when_no_hyde():
    """Base providers return no HyDE → exactly one retrieval, no fusion."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    calls: list[str] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        calls.append(text)
        return [_make_chunk()]

    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "How does it work?",
                    FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                )

    assert len(calls) == 1, "no HyDE → single raw retrieval, no second arm"
    assert result.citations, "raw-only path must still produce citations"


def test_base_provider_hyde_returns_empty():
    """The base LLMProvider yields no HyDE so it degrades to raw-only retrieval."""
    from app.rag.provider import LLMProvider

    class _Bare(LLMProvider):
        def generate(self, question, chunks):
            return ""

    assert _Bare().hyde("anything") == ""


def test_hyde_openai_compat_returns_empty_on_error(monkeypatch):
    """A failed HyDE generation must return '' so the pipeline cleanly degrades to
    raw-only instead of wasting a second identical retrieval."""
    import openai

    from app.rag.generation import _hyde_openai_compat

    class _Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("no network")

    monkeypatch.setattr(openai, "OpenAI", _Boom)
    assert _hyde_openai_compat("q?", base_url="x", api_key="y", model="m") == ""


# ---------------------------------------------------------------------------
# _extract_tags tests
# ---------------------------------------------------------------------------

def test_extract_tags_no_tags_returns_empty_list():
    from app.rag.pipeline import _extract_tags
    clean, tags = _extract_tags("What does Accelerate do?")
    assert tags == []
    assert clean == "What does Accelerate do?"


def test_extract_tags_single_tag_removed_from_clean():
    from app.rag.pipeline import _extract_tags
    clean, tags = _extract_tags("@accelerate what does it do?")
    assert "accelerate" in tags
    assert "@accelerate" not in clean


def test_extract_tags_uppercase_lowercased():
    from app.rag.pipeline import _extract_tags
    _, tags = _extract_tags("@Accelerate what?")
    assert tags == ["accelerate"]


def test_extract_tags_multiple_tags():
    from app.rag.pipeline import _extract_tags
    _, tags = _extract_tags("compare @accelerate and @action rules")
    assert set(tags) == {"accelerate", "action"}


def test_extract_tags_result_stripped():
    from app.rag.pipeline import _extract_tags
    clean, _ = _extract_tags("@foo bar")
    assert clean == clean.strip()


# ---------------------------------------------------------------------------
# answer_question — @tag integration tests
# ---------------------------------------------------------------------------

async def test_pipeline_tagged_chunks_prepend_before_semantic():
    """Tagged chunks (similarity=1.0) must appear before semantic chunks in citations."""
    from app.rag.retrieval import Chunk
    from tests.conftest import FakeEmbedder

    tagged_chunk = Chunk("tag_id", "Accelerate content", "Accelerate", None, "rulebook", 1.0)
    semantic_chunk = Chunk("sem_id", "Other content", "Other Rule", None, "rulebook", 0.7)

    with patch("app.rag.pipeline.tagged_lookup", return_value=[tagged_chunk]):
        with patch("app.rag.pipeline.hybrid_search", return_value=[semantic_chunk]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    from tests.conftest import FakeLLMProvider
                    result = await answer_question(
                        "@accelerate what does it do?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    assert result.citations[0].section == "Accelerate"


# ---------------------------------------------------------------------------
# _detect_keywords tests
# ---------------------------------------------------------------------------

def test_detect_keywords_finds_exact():
    from app.rag.pipeline import _detect_keywords
    assert "accelerate" in _detect_keywords("What does Accelerate do?")


def test_detect_keywords_case_insensitive():
    from app.rag.pipeline import _detect_keywords
    assert "accelerate" in _detect_keywords("WHAT DOES ACCELERATE DO?")


def test_detect_keywords_no_match():
    from app.rag.pipeline import _detect_keywords
    assert _detect_keywords("How many cards in a deck?") == []


def test_detect_keywords_multi_word():
    from app.rag.pipeline import _detect_keywords
    assert "quick-draw" in _detect_keywords("Explain Quick-Draw please")


def test_detect_keywords_multiple():
    from app.rag.pipeline import _detect_keywords
    result = _detect_keywords("Compare Accelerate and Action")
    assert "accelerate" in result and "action" in result



def test_detect_keywords_alias_action_phase():
    from app.rag.pipeline import _detect_keywords
    result = _detect_keywords("Which phase allows discretionary actions? Is it the Action Phase?")
    assert "main phase" in result
    assert "action phase" not in result


def test_detect_keywords_main_phase_direct():
    from app.rag.pipeline import _detect_keywords
    assert "main phase" in _detect_keywords("What can I do during the Main Phase?")


async def test_pipeline_auto_detects_keyword_without_tag():
    """A question without @tag but mentioning a keyword triggers tagged_lookup."""
    from app.rag.retrieval import Chunk
    from tests.conftest import FakeEmbedder

    tagged_chunk = Chunk("tag_id", "Accelerate content", "Accelerate", None, "rulebook", 1.0)

    with patch("app.rag.pipeline.tagged_lookup", return_value=[tagged_chunk]) as mock_lookup:
        with patch("app.rag.pipeline.hybrid_search", return_value=[]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    from tests.conftest import FakeLLMProvider
                    result = await answer_question(
                        "What does Accelerate do?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    mock_lookup.assert_called_once()
    assert result.citations[0].section == "Accelerate"


async def test_pipeline_card_mentions_passed_to_tagged_lookup_as_tags():
    """card_mentions from the request body must become tags for tagged_lookup."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.tagged_lookup", return_value=[]) as mock_lookup:
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    await answer_question(
                        "How does this card work?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                        card_mentions=["Yasuo"],
                    )

    mock_lookup.assert_called_once()
    _, tags_arg, _ = mock_lookup.call_args[0]
    assert "yasuo" in tags_arg


async def test_pipeline_card_mentions_lowercased():
    """Card mentions arrive in any case but must be normalised to lowercase tags."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.tagged_lookup", return_value=[]) as mock_lookup:
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    await answer_question(
                        "question?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                        card_mentions=["YASUO", "Shen"],
                    )

    _, tags_arg, _ = mock_lookup.call_args[0]
    assert "yasuo" in tags_arg and "shen" in tags_arg
    assert "YASUO" not in tags_arg and "Shen" not in tags_arg


async def test_pipeline_card_mentions_dedup_with_explicit_at_tag():
    """An explicit @Yasuo in the question + card_mentions=['Yasuo'] must produce only one 'yasuo' tag."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.tagged_lookup", return_value=[]) as mock_lookup:
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    await answer_question(
                        "@Yasuo can attack?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                        card_mentions=["Yasuo"],
                    )

    _, tags_arg, _ = mock_lookup.call_args[0]
    assert tags_arg.count("yasuo") == 1


async def test_pipeline_no_card_mentions_does_not_alter_existing_tag_flow():
    """Backwards-compat: when card_mentions is None, behavior must match the previous tag pipeline."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.tagged_lookup", return_value=[]) as mock_lookup:
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    await answer_question(
                        "@accelerate how does it work?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    _, tags_arg, _ = mock_lookup.call_args[0]
    assert tags_arg == ["accelerate"]


# ---------------------------------------------------------------------------
# Confidence honesty
#
# confidence must reflect the strength of REAL semantic retrieval (max cosine
# similarity), not the fabricated 1.0 of a tagged section match, and not the
# position-dependent first citation.
# ---------------------------------------------------------------------------

async def test_pipeline_confidence_not_inflated_by_tagged_match():
    """A tagged exact-match must NOT push confidence to 1.0 when the semantic
    signal is weak. Confidence reflects real cosine, not the section match."""
    from app.rag.retrieval import Chunk
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    tagged_chunk = Chunk("tag_id", "Accelerate content", "Accelerate", None, "rulebook", 1.0)
    weak_semantic = Chunk("sem_id", "Weakly related", "Other", None, "rulebook", 0.31)

    with patch("app.rag.pipeline.tagged_lookup", return_value=[tagged_chunk]):
        with patch("app.rag.pipeline.hybrid_search", return_value=[weak_semantic]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = await answer_question(
                        "@accelerate what does it do?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    assert result.confidence == 0.31


async def test_pipeline_confidence_is_max_semantic_cosine_not_first():
    """Confidence is the MAX cosine among semantic chunks, not citations[0]."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    chunks = [
        _make_chunk(section="A", similarity=0.5),
        _make_chunk(section="B", similarity=0.82),
        _make_chunk(section="C", similarity=0.6),
    ]
    # distinct ids so they don't dedup
    for i, c in enumerate(chunks):
        object.__setattr__(c, "id", f"id{i}")

    with patch("app.rag.pipeline.hybrid_search", return_value=chunks):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = await answer_question(
                    "How does it work?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                )

    assert result.confidence == 0.82


async def test_pipeline_confidence_zero_without_semantic_signal():
    """Tagged match but empty hybrid retrieval → no real cosine → confidence 0.0."""
    from app.rag.retrieval import Chunk
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    tagged_chunk = Chunk("tag_id", "Accelerate content", "Accelerate", None, "rulebook", 1.0)

    with patch("app.rag.pipeline.tagged_lookup", return_value=[tagged_chunk]):
        with patch("app.rag.pipeline.hybrid_search", return_value=[]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = await answer_question(
                        "@accelerate what does it do?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    assert result.confidence == 0.0


async def test_pipeline_tagged_deduplicates_with_semantic():
    """A chunk returned by both tagged_lookup and hybrid_search appears only once in citations."""
    from app.rag.retrieval import Chunk
    from tests.conftest import FakeEmbedder

    shared_chunk = Chunk("shared_id", "Accelerate content", "Accelerate", None, "rulebook", 1.0)
    semantic_dup = Chunk("shared_id", "Accelerate content", "Accelerate", None, "rulebook", 0.9)

    with patch("app.rag.pipeline.tagged_lookup", return_value=[shared_chunk]):
        with patch("app.rag.pipeline.hybrid_search", return_value=[semantic_dup]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    from tests.conftest import FakeLLMProvider
                    result = await answer_question(
                        "@accelerate",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    chunk_ids = [c.chunk_id for c in result.citations]
    assert chunk_ids.count("shared_id") == 1
