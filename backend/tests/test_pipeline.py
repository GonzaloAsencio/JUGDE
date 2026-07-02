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


# ---------------------------------------------------------------------------
# _has_exact_card_match — whole-word, not substring
#
# A substring test let tag "jhin" match section "Jhinx" and wrongly force
# confidence to 1.0. The match must be whole-word.
# ---------------------------------------------------------------------------

def test_exact_card_match_hits_on_whole_word():
    from app.rag.pipeline import _has_exact_card_match

    chunks = [_make_chunk(section="Jhin - The Virtuoso")]
    assert _has_exact_card_match(chunks, {"jhin"}) is True


def test_exact_card_match_ignores_substring_of_a_longer_name():
    from app.rag.pipeline import _has_exact_card_match

    chunks = [_make_chunk(section="Jhinx")]
    # "jhin" is a substring of "Jhinx" but not a whole word — must NOT match.
    assert _has_exact_card_match(chunks, {"jhin"}) is False


def test_exact_card_match_empty_tags_is_false():
    from app.rag.pipeline import _has_exact_card_match

    assert _has_exact_card_match([_make_chunk(section="Anything")], set()) is False


def test_exact_card_match_multiword_tag():
    from app.rag.pipeline import _has_exact_card_match

    chunks = [_make_chunk(section="Irelia - Blade Dancer")]
    assert _has_exact_card_match(chunks, {"blade dancer"}) is True


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
                result = answer_question(
                    "What is a rule?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert result.citations == []
    assert "I don't have enough information" in result.answer


async def test_pipeline_uses_explicit_corpus_version_without_mutating_settings():
    """The explicit corpus_version wins and the Settings singleton is left intact."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    settings = _fake_settings()
    settings.corpus_version = "settings-default"

    captured = {}

    def _capture(pool, embedding, query_text, corpus_version, **kwargs):
        captured["corpus_version"] = corpus_version
        return []

    with patch("app.rag.pipeline.hybrid_search", side_effect=_capture):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                answer_question(
                    "What is a rule?", FakeEmbedder(), MagicMock(), FakeLLMProvider(),
                    settings, corpus_version="explicit-v9",
                )

    assert captured["corpus_version"] == "explicit-v9"
    assert settings.corpus_version == "settings-default"  # not mutated


async def test_pipeline_latency_ms_populated():
    """latency_ms must be a non-negative integer in the response."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    settings = _fake_settings()

    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = answer_question(
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
                result = answer_question(
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
                    answer_question(
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
                result = answer_question(
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
                answer_question(
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
                result = answer_question(
                    "How does it work?",
                    FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                )

    assert len(calls) == 1, "no HyDE → single raw retrieval, no second arm"
    assert result.citations, "raw-only path must still produce citations"


async def test_pipeline_fusion_arms_fetch_deep_then_truncate_once():
    """In the HyDE fusion path each arm must fetch at top_k_fetch depth so a strong
    single-arm hit survives; fuse_results truncates ONCE to top_k. (B2: the double
    truncation at top_k dropped raw-rank-3 card chunks before fusion.)"""
    from tests.conftest import FakeEmbedder

    arm_top_ks: list[int] = []
    fuse_top_k: dict[str, int] = {}

    def fake_hybrid(pool, emb, text, cv, **kw):
        arm_top_ks.append(kw.get("top_k"))
        return [_make_chunk(section=text[:6])]

    def fake_fuse(primary, secondary, rrf_k=60, top_k=5):
        fuse_top_k["top_k"] = top_k
        return (primary + secondary)[:top_k]

    settings = _fake_settings()  # top_k=5, top_k_fetch=15
    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.fuse_results", side_effect=fake_fuse):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    answer_question(
                        "How does conquer work?",
                        FakeEmbedder(), MagicMock(), _HydeProvider(), settings,
                    )

    assert arm_top_ks == [15, 15], "both arms must fetch at top_k_fetch depth before fusing"
    assert fuse_top_k["top_k"] == 5, "fusion truncates exactly once to top_k"


async def test_pipeline_raw_only_arm_fetches_at_top_k():
    """No HyDE → the single arm fetches at top_k (no deep fetch needed)."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    arm_top_ks: list[int] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        arm_top_ks.append(kw.get("top_k"))
        return [_make_chunk()]

    settings = _fake_settings()  # top_k=5
    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                answer_question(
                    "How does it work?",
                    FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings,
                )

    assert arm_top_ks == [5], "raw-only arm fetches at top_k"


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
# _assemble_context tests
# ---------------------------------------------------------------------------

def _ctx_chunk(cid: str, source_type: str = "rulebook", sim: float = 0.5):
    from app.rag.retrieval import Chunk
    return Chunk(cid, f"content-{cid}", f"sec-{cid}", None, source_type, sim)


def test_assemble_context_no_tags_returns_semantic_bounded():
    from app.rag.pipeline import _assemble_context
    semantic = [_ctx_chunk("a"), _ctx_chunk("b"), _ctx_chunk("c")]
    out = _assemble_context([], semantic, [], top_k=2)
    assert [c.id for c in out] == ["a", "b"]


def test_assemble_context_explicit_prepended_before_semantic():
    """Explicit @tags keep their prepend priority (user-directed lookup)."""
    from app.rag.pipeline import _assemble_context
    explicit = [_ctx_chunk("t1")]
    semantic = [_ctx_chunk("s1"), _ctx_chunk("s2")]
    out = _assemble_context(explicit, semantic, [], top_k=5)
    assert out[0].id == "t1"


def test_assemble_context_explicit_reserves_one_semantic_slot():
    """Explicit tags cannot consume the whole budget — semantic keeps >=1 slot."""
    from app.rag.pipeline import _assemble_context
    explicit = [_ctx_chunk("t1"), _ctx_chunk("t2"), _ctx_chunk("t3")]
    semantic = [_ctx_chunk("s1")]
    out = _assemble_context(explicit, semantic, [], top_k=3)
    ids = [c.id for c in out]
    assert "s1" in ids
    assert len(out) == 3


def test_assemble_context_auto_never_displaces_semantic():
    """Auto keyword chunks fill only leftover budget; they never evict semantic."""
    from app.rag.pipeline import _assemble_context
    semantic = [_ctx_chunk("card1", "card"), _ctx_chunk("card2", "card"), _ctx_chunk("card3", "card")]
    auto = [_ctx_chunk("junk1", "rulebook"), _ctx_chunk("junk2", "rulebook")]
    out = _assemble_context([], semantic, auto, top_k=3)
    assert [c.id for c in out] == ["card1", "card2", "card3"]


def test_assemble_context_auto_fills_leftover():
    from app.rag.pipeline import _assemble_context
    semantic = [_ctx_chunk("s1")]
    auto = [_ctx_chunk("a1")]
    out = _assemble_context([], semantic, auto, top_k=3)
    assert [c.id for c in out] == ["s1", "a1"]


def test_assemble_context_never_exceeds_top_k():
    from app.rag.pipeline import _assemble_context
    explicit = [_ctx_chunk(f"e{i}") for i in range(4)]
    semantic = [_ctx_chunk(f"s{i}") for i in range(4)]
    auto = [_ctx_chunk(f"a{i}") for i in range(4)]
    out = _assemble_context(explicit, semantic, auto, top_k=3)
    assert len(out) == 3


def test_assemble_context_dedups_across_sources():
    from app.rag.pipeline import _assemble_context
    explicit = [_ctx_chunk("shared")]
    semantic = [_ctx_chunk("shared"), _ctx_chunk("s2")]
    out = _assemble_context(explicit, semantic, [], top_k=5)
    assert [c.id for c in out] == ["shared", "s2"]


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
                    result = answer_question(
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


def test_detect_keywords_no_substring_false_positive_ready():
    """'already' must NOT trigger the 'ready' keyword (eval-025 false positive)."""
    from app.rag.pipeline import _detect_keywords
    assert "ready" not in _detect_keywords("even if she is already on the board")


def test_detect_keywords_no_substring_false_positive_equip():
    """'equipment' must NOT trigger the 'equip' keyword (eval-021 false positive)."""
    from app.rag.pipeline import _detect_keywords
    assert "equip" not in _detect_keywords("when he is mighty with an equipment")


def test_detect_keywords_whole_word_still_matches():
    """Whole-word occurrences must still be detected."""
    from app.rag.pipeline import _detect_keywords
    assert "draw" in _detect_keywords("tap 2 runes to draw 2 cards")
    assert "mighty" in _detect_keywords("when he is mighty with gear")


def test_detect_keywords_hyphenated_still_matches():
    from app.rag.pipeline import _detect_keywords
    assert "quick-draw" in _detect_keywords("Explain Quick-Draw please")


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
                    result = answer_question(
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
                    answer_question(
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
                    answer_question(
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
                    answer_question(
                        "@Yasuo can attack?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                        card_mentions=["Yasuo"],
                    )

    _, tags_arg, _ = mock_lookup.call_args[0]
    assert tags_arg.count("yasuo") == 1


async def test_pipeline_auto_detected_card_becomes_directed_tag():
    """A card named in the question (no @tag, no card_mentions) must be detected
    against the corpus vocabulary and passed to tagged_lookup as a directed tag —
    this is the hard-bucket fix (cards absent from semantic retrieval)."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.load_card_names", return_value=("Marching Orders", "Tideturner")):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[]) as mock_lookup:
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                with patch("app.rag.pipeline.get_cached", return_value=None):
                    with patch("app.rag.pipeline.set_cached"):
                        from app.rag.pipeline import answer_question
                        answer_question(
                            "If I play Marching Orders with Repeat, what happens?",
                            FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                        )

    # First tagged_lookup call is the directed-tags lookup (explicit + detected cards).
    _, directed_arg, _ = mock_lookup.call_args_list[0][0]
    assert "marching orders" in directed_arg


async def test_pipeline_card_detection_failure_does_not_break_query():
    """If the vocabulary load raises, the query still answers (best-effort feature)."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.load_card_names", side_effect=RuntimeError("db down")):
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = answer_question(
                        "How does this work?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    assert result.citations, "query must still answer when card detection fails"


async def test_pipeline_no_card_mentions_does_not_alter_existing_tag_flow():
    """Backwards-compat: when card_mentions is None, behavior must match the previous tag pipeline."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    with patch("app.rag.pipeline.tagged_lookup", return_value=[]) as mock_lookup:
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    answer_question(
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
                    result = answer_question(
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
                result = answer_question(
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
                    result = answer_question(
                        "@accelerate what does it do?",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    assert result.confidence == 0.0


async def test_pipeline_exact_card_match_yields_high_confidence():
    """A card resolved by exact-name detection is the most precise retrieval
    possible — its confidence must be high even when the semantic cosine is weak.
    This is distinct from a generic @tag match (which must NOT inflate)."""
    from app.rag.retrieval import Chunk
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    card_chunk = Chunk("card_id", "Kha'Zix content", "Kha'Zix - Mutating Horror", None, "card", 0.0)
    weak_semantic = Chunk("sem_id", "Weakly related", "Other", None, "rulebook", 0.4)

    with patch("app.rag.pipeline.load_card_names", return_value=()):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[card_chunk]):
            with patch("app.rag.pipeline.hybrid_search", return_value=[weak_semantic]):
                with patch("app.rag.pipeline.get_cached", return_value=None):
                    with patch("app.rag.pipeline.set_cached"):
                        from app.rag.pipeline import answer_question
                        result = answer_question(
                            "what does this card do?",
                            FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                            card_mentions=["Kha'Zix - Mutating Horror"],
                        )

    assert result.confidence == 1.0


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
                    result = answer_question(
                        "@accelerate",
                        FakeEmbedder(), MagicMock(), FakeLLMProvider(), _fake_settings(),
                    )

    chunk_ids = [c.chunk_id for c in result.citations]
    assert chunk_ids.count("shared_id") == 1
