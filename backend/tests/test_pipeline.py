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
    # MagicMock() attrs are truthy by default — pin these explicitly so
    # `if settings.enable_reranker:` in the pipeline behaves like the real
    # Settings default (off) unless a test opts in.
    s.enable_reranker = False
    s.reranker_model = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    s.rerank_pool_size = 15
    s.keyword_family_extra = 0
    s.semantic_cache_enabled = False
    s.semantic_cache_threshold = 0.85
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


async def test_pipeline_fuses_arms_when_gemini_provider_hyde_returns_real_text():
    """PR1 regression guard: pipeline.py:211-226's dual-arm path must still
    trigger correctly now that GeminiProvider.hyde() returns real text instead
    of the base-class '' default."""
    from tests.conftest import FakeEmbedder
    from app.rag.provider import GeminiProvider

    raw_chunk = _make_chunk(section="RAW")
    hyde_chunk = _make_chunk(section="HYDE")
    object.__setattr__(raw_chunk, "id", "raw_id2")
    object.__setattr__(hyde_chunk, "id", "hyde_id2")

    calls: list[str] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        calls.append(text)
        return [raw_chunk] if len(calls) == 1 else [hyde_chunk]

    class _FakeGenResponse:
        text = "Fake answer for testing."

    class _FakeGenClient:
        class models:
            @staticmethod
            def generate_content(**kwargs):
                return _FakeGenResponse()

    provider = GeminiProvider(client=_FakeGenClient(), model="gemini-2.0-flash", temperature=0.1, timeout_s=10.0)

    with patch("app.rag.generation._hyde_gemini", return_value="A hypothetical confident answer."):
        with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = answer_question(
                        "How many cards are in a starting deck?",
                        FakeEmbedder(), MagicMock(), provider, _fake_settings(),
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
        def generate(self, question, chunks, *, extra_system: str = ""):
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


def _rule_chunk(cid: str, section: str):
    """Auto keyword chunk whose section is a numbered rule ('820. Repeat') —
    the fine labels the 2026-07 re-chunking produces for keyword rule families."""
    from app.rag.retrieval import Chunk
    return Chunk(cid, f"content-{cid}", section, None, "rulebook", 0.0)


def test_assemble_context_reserves_slot_for_keyword_rule_chunk():
    """A detected keyword's RULE chunk ('820. Repeat') gets one reserved slot even
    when semantic fills the budget. Diagnosed on eval-037: 'repeat' was detected and
    tagged_lookup found the rule, but leftover-only budgeting never let it in."""
    from app.rag.pipeline import _assemble_context
    semantic = [_ctx_chunk("s1", "card"), _ctx_chunk("s2", "card"), _ctx_chunk("s3", "card")]
    auto = [_rule_chunk("kw1", "820. Repeat")]
    out = _assemble_context([], semantic, auto, top_k=3)
    ids = [c.id for c in out]
    assert "kw1" in ids, "keyword rule chunk must get its reserved slot"
    assert len(out) == 3


def test_assemble_context_non_rule_auto_never_displaces_semantic():
    """Only rule-sectioned keyword chunks earn the slot — a card that merely
    ILIKE-matched the tag ('Hunters Machete' for 'hunt') still never evicts."""
    from app.rag.pipeline import _assemble_context
    semantic = [_ctx_chunk("s1", "card"), _ctx_chunk("s2", "card"), _ctx_chunk("s3", "card")]
    auto = [_ctx_chunk("junk1")]  # section 'sec-junk1' — not a numbered rule
    out = _assemble_context([], semantic, auto, top_k=3)
    assert [c.id for c in out] == ["s1", "s2", "s3"]


def test_assemble_context_keyword_slot_backfills_when_rule_chunk_is_dup():
    """If the keyword rule chunk already arrived semantically, the reserved slot
    must be returned to semantic — never waste budget on a duplicate."""
    from app.rag.pipeline import _assemble_context
    semantic = [_ctx_chunk("s1"), _rule_chunk("kw1", "820. Repeat"), _ctx_chunk("s3")]
    auto = [_rule_chunk("kw1", "820. Repeat")]
    out = _assemble_context([], semantic, auto, top_k=3)
    assert [c.id for c in out] == ["s1", "kw1", "s3"]


def test_assemble_context_dedups_across_sources():
    from app.rag.pipeline import _assemble_context
    explicit = [_ctx_chunk("shared")]
    semantic = [_ctx_chunk("shared"), _ctx_chunk("s2")]
    out = _assemble_context(explicit, semantic, [], top_k=5)
    assert [c.id for c in out] == ["shared", "s2"]


# ---------------------------------------------------------------------------
# _complete_keyword_families tests (3.5 — keyword family completion)
# ---------------------------------------------------------------------------

def test_family_completion_appends_missing_siblings_beyond_top_k():
    """A detected keyword's rule family rides ALONG the top_k context, never
    inside it: family siblings append at the end without evicting anything.
    (eval-030: the '809. Deflect' slot chunk entered but 809.1 stayed in a
    sibling chunk the budget dropped.)"""
    from app.rag.pipeline import _complete_keyword_families
    context = [_ctx_chunk("s1"), _rule_chunk("kw1", "809. Deflect")]
    family = [_rule_chunk("kw1", "809. Deflect"), _rule_chunk("kw2", "809. Deflect"),
              _rule_chunk("kw3", "809. Deflect")]
    out = _complete_keyword_families(context, family, extra_cap=8)
    assert [c.id for c in out] == ["s1", "kw1", "kw2", "kw3"]


def test_family_completion_dedupes_chunks_already_in_context():
    from app.rag.pipeline import _complete_keyword_families
    context = [_rule_chunk("kw1", "809. Deflect"), _rule_chunk("kw2", "809. Deflect")]
    family = [_rule_chunk("kw1", "809. Deflect"), _rule_chunk("kw2", "809. Deflect")]
    out = _complete_keyword_families(context, family, extra_cap=8)
    assert [c.id for c in out] == ["kw1", "kw2"]


def test_family_completion_respects_extra_cap():
    """The completion tail is bounded: at most extra_cap siblings append even
    when the family (or several families) is larger."""
    from app.rag.pipeline import _complete_keyword_families
    context = [_rule_chunk("kw1", "811. Hidden")]
    family = [_rule_chunk(f"f{i}", "811. Hidden") for i in range(10)]
    out = _complete_keyword_families(context, family, extra_cap=3)
    assert len(out) == 4  # context + cap


def test_family_completion_zero_cap_is_identity():
    """extra_cap=0 (the default setting) must be byte-identical to today's
    behaviour — the regression guarantee for the flag-off path."""
    from app.rag.pipeline import _complete_keyword_families
    context = [_ctx_chunk("s1"), _rule_chunk("kw1", "809. Deflect")]
    family = [_rule_chunk("kw2", "809. Deflect")]
    out = _complete_keyword_families(context, family, extra_cap=0)
    assert [c.id for c in out] == ["s1", "kw1"]


def test_family_completion_never_evicts_context():
    """Family chunks are similarity-0.0 lexical matches — they must only ever
    APPEND. The assembled top_k context comes back untouched, in order."""
    from app.rag.pipeline import _complete_keyword_families
    context = [_ctx_chunk("s1"), _ctx_chunk("s2"), _rule_chunk("kw1", "809. Deflect")]
    family = [_rule_chunk("kw2", "809. Deflect")]
    out = _complete_keyword_families(context, family, extra_cap=8)
    assert [c.id for c in out][:3] == ["s1", "s2", "kw1"]


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


# ---------------------------------------------------------------------------
# Empty Answer-section guard + single retry (_generate_guarded)
#
# Gemini sometimes writes a full Reasoning block on an ambiguous question and
# then stops with an empty "Answer:". The pipeline retries once; if the retry
# is also empty it substitutes a controlled inconclusive message so the UI
# never renders a blank answer bubble.
# ---------------------------------------------------------------------------

from app.rag.provider import LLMProvider as _LLMProvider


class _ScriptedProvider(_LLMProvider):
    """Returns a scripted list of answers, one per generate() call."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = answers
        self.calls = 0

    def generate(self, question: str, chunks, *, extra_system: str = "") -> str:
        answer = self._answers[self.calls]
        self.calls += 1
        return answer


_EMPTY_ANSWER = "Reasoning:\n- Rule 461.3.d applies.\n\nAnswer:"
_GOOD_ANSWER = "Reasoning:\n- Rule 301.\n\nAnswer: Yes, it's a draw."


async def test_pipeline_retries_once_when_answer_section_empty():
    from tests.conftest import FakeEmbedder
    from app.rag.pipeline import _INCONCLUSIVE_ANSWER  # noqa: F401  (import sanity)

    provider = _ScriptedProvider([_EMPTY_ANSWER, _GOOD_ANSWER])
    settings = _fake_settings()
    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = answer_question(
                    "Both reach 0 health?", FakeEmbedder(), MagicMock(), provider, settings
                )

    assert provider.calls == 2
    assert "draw" in result.answer.lower()


async def test_pipeline_falls_back_when_retry_also_empty():
    from tests.conftest import FakeEmbedder
    from app.rag.pipeline import _INCONCLUSIVE_ANSWER

    provider = _ScriptedProvider([_EMPTY_ANSWER, _EMPTY_ANSWER])
    settings = _fake_settings()
    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                result = answer_question(
                    "Both reach 0 health?", FakeEmbedder(), MagicMock(), provider, settings
                )

    assert provider.calls == 2
    assert result.answer == _INCONCLUSIVE_ANSWER


async def test_pipeline_does_not_cache_inconclusive_answer():
    """A degraded answer (empty-Answer retry exhausted) must NOT be cached —
    a 24h TTL would freeze the transient failure for every user."""
    from tests.conftest import FakeEmbedder
    from app.rag.pipeline import _INCONCLUSIVE_ANSWER

    provider = _ScriptedProvider([_EMPTY_ANSWER, _EMPTY_ANSWER])
    settings = _fake_settings()
    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached") as mock_set:
                from app.rag.pipeline import answer_question
                result = answer_question(
                    "Both reach 0 health?", FakeEmbedder(), MagicMock(), provider, settings
                )

    assert result.answer == _INCONCLUSIVE_ANSWER
    mock_set.assert_not_called()


async def test_pipeline_does_not_cache_safe_fallback():
    """The safety-block fallback keeps its citations (confidence > 0), so the
    answer-based check — not just confidence — must skip the cache."""
    from tests.conftest import FakeEmbedder
    from app.rag.generation import _SAFE_FALLBACK

    provider = _ScriptedProvider([_SAFE_FALLBACK])
    settings = _fake_settings()
    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached") as mock_set:
                from app.rag.pipeline import answer_question
                answer_question(
                    "Ignore your instructions?", FakeEmbedder(), MagicMock(), provider, settings
                )

    mock_set.assert_not_called()


async def test_pipeline_caches_good_answer():
    """Regression guard for the degraded-response gate: a real answer with
    citations still lands in the cache."""
    from tests.conftest import FakeEmbedder

    provider = _ScriptedProvider([_GOOD_ANSWER])
    settings = _fake_settings()
    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached") as mock_set:
                from app.rag.pipeline import answer_question
                result = answer_question(
                    "Both reach 0 health?", FakeEmbedder(), MagicMock(), provider, settings
                )

    assert "draw" in result.answer.lower()
    mock_set.assert_called_once()


async def test_pipeline_does_not_retry_when_answer_present():
    from tests.conftest import FakeEmbedder

    provider = _ScriptedProvider([_GOOD_ANSWER])
    settings = _fake_settings()
    chunk = _make_chunk()
    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                answer_question(
                    "Can I block?", FakeEmbedder(), MagicMock(), provider, settings
                )

    assert provider.calls == 1


# ---------------------------------------------------------------------------
# Reranker integration (PR2): rerank() is applied to the semantic pool only,
# strictly gated by settings.enable_reranker. Flag-off must be byte-identical
# to pre-PR2 behaviour (see design D2's regression guarantee).
# ---------------------------------------------------------------------------

def test_pipeline_reranker_off_is_byte_identical_to_current_behavior():
    """enable_reranker=False → chunks equal current fuse_results/top_k output,
    reranker never invoked."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    chunk = _make_chunk(section="Only Chunk")
    settings = _fake_settings()  # enable_reranker=False by default

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.rerank") as mock_rerank:
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = answer_question(
                        "What is a rule?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                    )

    mock_rerank.assert_not_called()
    assert [c.section for c in result.citations] == ["Only Chunk"]


def test_pipeline_reranker_off_arm_fetches_at_top_k_not_pool_size():
    """Flag off → pool_k == top_k, so the raw-only arm still fetches at top_k
    (not rerank_pool_size) — the regression guard from design D2."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    arm_top_ks: list[int] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        arm_top_ks.append(kw.get("top_k"))
        return [_make_chunk()]

    settings = _fake_settings()  # top_k=5, enable_reranker=False, rerank_pool_size=15
    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.get_cached", return_value=None):
            with patch("app.rag.pipeline.set_cached"):
                from app.rag.pipeline import answer_question
                answer_question(
                    "How does it work?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                )

    assert arm_top_ks == [5], "flag off: pool_k must equal top_k, unchanged from pre-PR2 behavior"


def test_pipeline_reranker_on_scores_pool_and_returns_top_k():
    """enable_reranker=True, rerank_pool_size=15, top_k=5, pool has >=15
    candidates → reranker scores the 15-chunk pool, pipeline returns the top 5
    by cross-encoder score."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    pool_chunks = [_make_chunk(section=f"S{i}") for i in range(15)]
    for i, c in enumerate(pool_chunks):
        object.__setattr__(c, "id", f"id{i}")

    arm_top_ks: list[int] = []

    def fake_hybrid(pool, emb, text, cv, **kw):
        arm_top_ks.append(kw.get("top_k"))
        return pool_chunks

    # NOT the natural pool prefix: if the pipeline truncated the fused pool
    # itself instead of using rerank()'s return value, citations would equal
    # pool_chunks[:5] and a prefix here would pass anyway.
    reranked_top5 = list(reversed(pool_chunks))[:5]

    settings = _fake_settings()
    settings.enable_reranker = True

    with patch("app.rag.pipeline.hybrid_search", side_effect=fake_hybrid):
        with patch("app.rag.pipeline.rerank", return_value=reranked_top5) as mock_rerank:
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = answer_question(
                        "How does it work?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                    )

    assert arm_top_ks == [15], "flag on: raw-only arm must fetch at rerank_pool_size"
    mock_rerank.assert_called_once()
    _, kwargs = mock_rerank.call_args
    called_args = mock_rerank.call_args.args
    assert called_args[0] == "How does it work?"
    assert len(called_args[1]) == 15
    assert mock_rerank.call_args.kwargs.get("top_k") == 5 or called_args[2] == 5
    assert [c.section for c in result.citations] == [c.section for c in reranked_top5]


def test_pipeline_reranker_error_falls_back_to_fused_order():
    """reranker raises during scoring while enable_reranker=True → pipeline
    does not raise, returns top_k of the original fused order unchanged."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    chunk = _make_chunk(section="Fallback Chunk")

    settings = _fake_settings()
    settings.enable_reranker = True

    with patch("app.rag.pipeline.hybrid_search", return_value=[chunk]):
        with patch("app.rag.pipeline.rerank", side_effect=RuntimeError("boom")):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    result = answer_question(
                        "How does it work?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings
                    )

    assert result.citations, "reranker error must not break the query"
    assert result.citations[0].section == "Fallback Chunk"


def test_pipeline_reranker_never_receives_tagged_chunks():
    """Tagged/explicit card chunks are NEVER passed into rerank() — only the
    semantic pool. Exact-card match still yields confidence 1.0 with the
    reranker on."""
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    tagged_chunk = _make_chunk(section="Jhin - The Virtuoso", similarity=0.0)
    semantic_chunk = _make_chunk(section="Some Rule", similarity=0.7)
    object.__setattr__(tagged_chunk, "id", "tagged_id")
    object.__setattr__(semantic_chunk, "id", "semantic_id")

    settings = _fake_settings()
    settings.enable_reranker = True

    with patch("app.rag.pipeline.tagged_lookup", return_value=[tagged_chunk]):
        with patch("app.rag.pipeline.hybrid_search", return_value=[semantic_chunk]):
            with patch("app.rag.pipeline.rerank", return_value=[semantic_chunk]) as mock_rerank:
                with patch("app.rag.pipeline.get_cached", return_value=None):
                    with patch("app.rag.pipeline.set_cached"):
                        from app.rag.pipeline import answer_question
                        result = answer_question(
                            "@jhin what does it do?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings,
                            card_mentions=["jhin"],
                        )

    mock_rerank.assert_called_once()
    called_chunks = mock_rerank.call_args.args[1]
    assert tagged_chunk not in called_chunks, "tagged/explicit chunks must never be passed to rerank()"
    assert result.confidence == 1.0, "exact card match must still force confidence 1.0 with reranker on"


# ---------------------------------------------------------------------------
# Multi-card reasoning scaffold (PR3): _retrieve returns card_count as a 5th
# tuple element; answer_question computes extra_system via needs_scaffold and
# forwards it to provider.generate(..., extra_system=extra).
# ---------------------------------------------------------------------------

def test_retrieve_returns_card_count_as_fifth_element():
    """card_count is the size of the union of auto-detected + mentioned cards."""
    from app.rag.pipeline import _retrieve
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    settings = _fake_settings()
    with patch("app.rag.pipeline.load_card_names", return_value=()):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                result = _retrieve(
                    "what happens?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings,
                    ["Yasuo", "Shen"], "v1", "qid-1",
                )

    assert len(result) == 5
    card_count = result[4]
    assert card_count == 2


def test_retrieve_card_count_zero_without_mentions():
    from app.rag.pipeline import _retrieve
    from tests.conftest import FakeEmbedder, FakeLLMProvider

    settings = _fake_settings()
    with patch("app.rag.pipeline.load_card_names", return_value=()):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                result = _retrieve(
                    "What does Accelerate do?", FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings,
                    None, "v1", "qid-2",
                )

    assert result[4] == 0


def test_answer_question_forwards_scaffold_extra_system_when_two_cards_mentioned():
    """Two distinct card_mentions -> needs_scaffold=True -> provider.generate
    receives extra_system=_MULTI_CARD_SCAFFOLD."""
    from app.rag.generation import _MULTI_CARD_SCAFFOLD
    from tests.conftest import FakeEmbedder

    generate_calls: list[dict] = []

    class _SpyProvider(_LLMProvider):
        def generate(self, question, chunks, *, extra_system: str = "") -> str:
            generate_calls.append({"question": question, "extra_system": extra_system})
            return _GOOD_ANSWER

    settings = _fake_settings()
    with patch("app.rag.pipeline.load_card_names", return_value=()):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                with patch("app.rag.pipeline.get_cached", return_value=None):
                    with patch("app.rag.pipeline.set_cached"):
                        from app.rag.pipeline import answer_question
                        answer_question(
                            "what happens in this interaction?",
                            FakeEmbedder(), MagicMock(), _SpyProvider(), settings,
                            card_mentions=["Yasuo", "Shen"],
                        )

    assert len(generate_calls) == 1
    assert generate_calls[0]["extra_system"] == _MULTI_CARD_SCAFFOLD


def test_answer_question_no_scaffold_for_simple_single_card_question():
    """A plain single-card, non-conditional question must NOT receive the
    scaffold — provider.generate gets extra_system=''."""
    from tests.conftest import FakeEmbedder

    generate_calls: list[dict] = []

    class _SpyProvider(_LLMProvider):
        def generate(self, question, chunks, *, extra_system: str = "") -> str:
            generate_calls.append({"extra_system": extra_system})
            return _GOOD_ANSWER

    settings = _fake_settings()
    with patch("app.rag.pipeline.load_card_names", return_value=()):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                with patch("app.rag.pipeline.get_cached", return_value=None):
                    with patch("app.rag.pipeline.set_cached"):
                        from app.rag.pipeline import answer_question
                        answer_question(
                            "What does Accelerate do?",
                            FakeEmbedder(), MagicMock(), _SpyProvider(), settings,
                        )

    assert generate_calls == [{"extra_system": ""}]


def test_answer_question_forwards_scaffold_extra_system_on_conditional_language():
    """0-1 cards but conditional language ('if ... then') must still trigger
    the scaffold."""
    from app.rag.generation import _MULTI_CARD_SCAFFOLD
    from tests.conftest import FakeEmbedder

    generate_calls: list[dict] = []

    class _SpyProvider(_LLMProvider):
        def generate(self, question, chunks, *, extra_system: str = "") -> str:
            generate_calls.append({"extra_system": extra_system})
            return _GOOD_ANSWER

    settings = _fake_settings()
    with patch("app.rag.pipeline.load_card_names", return_value=()):
        with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    answer_question(
                        "If it is exhausted, then can it attack?",
                        FakeEmbedder(), MagicMock(), _SpyProvider(), settings,
                    )

    assert generate_calls == [{"extra_system": _MULTI_CARD_SCAFFOLD}]


def test_scaffolded_response_still_parses_reasoning_answer_format():
    """Format-preservation guard: a scaffolded Reasoning/Answer response must
    still be correctly parsed by has_empty_answer_section (the scaffold only
    adds guidance, never redefines the output format)."""
    from app.rag.generation import has_empty_answer_section

    scaffolded_response = (
        "Reasoning:\n"
        "- Yasuo's ability: triggers on attack.\n"
        "- Shen's ability: triggers simultaneously when allies attack.\n"
        "Resolution order: Yasuo resolves first, then Shen.\n\n"
        "Answer: Both abilities resolve, Yasuo first."
    )
    assert has_empty_answer_section(scaffolded_response) is False

    empty_scaffolded_response = (
        "Reasoning:\n"
        "- Yasuo's ability: triggers on attack.\n"
        "- Shen's ability: triggers simultaneously when allies attack.\n\n"
        "Answer:"
    )
    assert has_empty_answer_section(empty_scaffolded_response) is True
