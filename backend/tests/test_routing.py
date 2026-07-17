"""Tests for hard-query routing (improvement plan 4.2 + 4.3).

Hard multi-entity questions fail on reasoning, not retrieval (probe
2026-07-12: with the FULL rulebook in context, flash-lite still misses
eval-014/017; gemini-3.5-flash with thinking answers all 4 residual misses
3/3). The routing lever: a deterministic classifier (zero LLM calls) sends
hard queries to a thinking model with a stuffed context — every detected
card's section plus the entire rulebook — while easy queries keep the
existing RAG path untouched. Flag off by default: the pipeline must be
byte-identical to pre-routing behaviour until an eval gate flips it.
"""
from unittest.mock import MagicMock, patch

from app.rag.pipeline import _KNOWN_KEYWORDS
from app.rag.retrieval import Chunk


# ---------------------------------------------------------------------------
# is_hard_query — deterministic classifier
#
# Thresholds calibrated on the annotated eval set (2026-07-12): cards >= 2 OR
# (a card plus >= 2 keywords) catches all 4 residual misses (eval-014/015/017/
# 019) plus 10 more hard/medium questions and ZERO easy ones. Question length
# was evaluated as a third signal and rejected: it adds only marginal routes.
# ---------------------------------------------------------------------------

def test_two_cards_is_hard():
    from app.rag.routing import is_hard_query

    assert is_hard_query(card_count=2, keyword_count=0) is True


def test_card_plus_two_keywords_is_hard():
    from app.rag.routing import is_hard_query

    # eval-015 shape: one card (Vex Apathetic) + two keywords (stun, ambush).
    assert is_hard_query(card_count=1, keyword_count=2) is True


def test_keywords_without_a_card_are_not_hard():
    from app.rag.routing import is_hard_query

    # The keyword vocabulary contains everyday words (draw, discard, token):
    # "when do I draw and when do I discard?" is an easy question that must
    # NOT pay the thinking-model latency. On the eval set every 0-card
    # question has at most 1 keyword, so this costs no target coverage.
    assert is_hard_query(card_count=0, keyword_count=2) is False


def test_one_card_one_keyword_is_not_hard():
    from app.rag.routing import is_hard_query

    # eval-020/030/037 shape. The original note here said eval-030 was "answered
    # correctly today by keyword family completion", so routing it would spend
    # quota for nothing — that was WRONG, and measured so on 2026-07-16: family
    # completion brings 809.1/809.1.a but NOT 365.1, so eval-030 is missing a
    # gold rule. This cell is exactly what `relaxed=True` opens (plan 3.11.1a);
    # the default stays False until the generation gate says otherwise.
    assert is_hard_query(card_count=1, keyword_count=1) is False


def test_no_signals_is_not_hard():
    from app.rag.routing import is_hard_query

    assert is_hard_query(card_count=0, keyword_count=0) is False


# ---------------------------------------------------------------------------
# relaxed=True — plan 3.11.1 lever (a), flag OFF by default
#
# Probed 3W/0L before any of this was written (scripts/routing_threshold_probe):
# opening the (1 card, 1 keyword) cell brings eval-020's 383.3.d, eval-030's
# 365.1 and eval-037's 131.4+425 into the context, and costs no gold ref
# anywhere. Coverage 22/26 -> 25/26. The generation gate still owes a real eval
# run, so the flag ships OFF.
# ---------------------------------------------------------------------------

def test_relaxed_routes_one_card_one_keyword():
    from app.rag.routing import is_hard_query

    assert is_hard_query(card_count=1, keyword_count=1, relaxed=True) is True


def test_relaxed_still_requires_a_card():
    from app.rag.routing import is_hard_query

    # The card requirement is what keeps "when do I draw and when do I discard?"
    # off the thinking model — the keyword vocabulary is full of everyday words.
    # Relaxing the keyword count must never relax this.
    assert is_hard_query(card_count=0, keyword_count=1, relaxed=True) is False
    assert is_hard_query(card_count=0, keyword_count=5, relaxed=True) is False


def test_relaxed_defaults_to_off():
    from app.rag.routing import is_hard_query

    # The regression guarantee: callers that don't opt in are byte-identical.
    assert is_hard_query(card_count=1, keyword_count=1) is False


def test_relaxed_only_moves_the_one_card_one_keyword_cell():
    from app.rag.routing import is_hard_query

    # Pins the blast radius to a single cell. Anything else flipping means the
    # flag changes more than it was measured to change.
    diffs = [
        (c, k)
        for c in range(5) for k in range(5)
        if is_hard_query(card_count=c, keyword_count=k)
        != is_hard_query(card_count=c, keyword_count=k, relaxed=True)
    ]
    assert diffs == [(1, 1)]


# ---------------------------------------------------------------------------
# build_stuffed_chunks — card sections + full rulebook
# ---------------------------------------------------------------------------

def test_stuffed_chunks_end_with_the_full_rulebook():
    from app.rag.routing import RULEBOOK_CHUNK_ID, build_stuffed_chunks

    chunks = build_stuffed_chunks("Can I attack twice?", known_keywords=_KNOWN_KEYWORDS)

    assert chunks is not None
    last = chunks[-1]
    assert last.id == RULEBOOK_CHUNK_ID
    assert last.source_type == "rulebook"
    # The whole rulebook, not a chunk of it.
    assert len(last.content) > 100_000


def test_stuffed_chunks_include_detected_card_sections_first():
    from app.rag.routing import build_stuffed_chunks

    question = (
        "My opponent controls Vex Apathetic. I play Tideturner on my own turn. "
        "Can Tideturner move before Vex's stun resolves?"
    )
    chunks = build_stuffed_chunks(question, known_keywords=_KNOWN_KEYWORDS)

    assert chunks is not None
    card_sections = [c.section for c in chunks if c.source_type == "card"]
    assert "Vex Apathetic" in card_sections
    assert "Tideturner" in card_sections
    # Cards prepend (mirrors production's explicit-chunk ordering); rulebook closes.
    assert chunks[-1].source_type == "rulebook"
    assert all(c.source_type == "card" for c in chunks[:-1])


def test_stuffed_chunks_returns_none_when_rulebook_file_missing():
    """Never-raise: a missing data file degrades to the normal RAG path."""
    from app.rag import routing

    with patch.object(routing, "_load_rulebook", side_effect=OSError("gone")):
        assert routing.build_stuffed_chunks("Any question?", known_keywords=frozenset()) is None


def test_stuffed_chunks_include_extra_card_names_absent_from_the_prose():
    """A terse question plus explicit card_mentions can classify as hard; the
    mentioned cards must reach the stuffed context even when the prose never
    names them (case-insensitive, deduped against prose detections)."""
    from app.rag.routing import build_stuffed_chunks

    chunks = build_stuffed_chunks(
        "Can these two interact during combat?",
        known_keywords=_KNOWN_KEYWORDS,
        extra_card_names=("vex apathetic", "Tideturner"),
    )

    assert chunks is not None
    card_sections = [c.section for c in chunks if c.source_type == "card"]
    assert card_sections == ["Vex Apathetic", "Tideturner"]


def test_stuffed_chunks_dedupe_extra_names_already_detected_in_prose():
    from app.rag.routing import build_stuffed_chunks

    question = "Does Vex Apathetic stun my unit?"
    chunks = build_stuffed_chunks(
        question, known_keywords=_KNOWN_KEYWORDS, extra_card_names=("VEX APATHETIC",)
    )

    assert chunks is not None
    card_sections = [c.section for c in chunks if c.source_type == "card"]
    assert card_sections.count("Vex Apathetic") == 1


# ---------------------------------------------------------------------------
# Settings — flag on by default after the 2026-07-13 prod gate, same pattern
# as the reranker flip
# ---------------------------------------------------------------------------

def test_settings_default_routing_on(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("HARD_QUERY_ROUTING", raising=False)
    s = Settings(_env_file=None, database_url="postgresql://fake:fake@localhost/fake", gemini_api_key="fake")

    assert s.hard_query_routing is True
    assert s.hard_gemini_model == "gemini-3.5-flash"
    assert s.hard_timeout_s == 90.0
    assert s.hard_max_output_tokens == 8192


def test_routing_flag_without_gemini_key_refuses_to_start():
    """Fail-closed: the hard provider is Gemini-only. An operator who flips
    HARD_QUERY_ROUTING without a GEMINI_API_KEY must get a loud startup error,
    not a pipeline that silently never routes (prod runs openai_compat/Groq as
    the MAIN provider — the gemini key is exactly the thing that can be absent)."""
    import pytest

    from app.config import Settings

    with pytest.raises(ValueError, match="hard_query_routing requires gemini_api_key"):
        Settings(
            _env_file=None,
            database_url="postgresql://fake:fake@localhost/fake",
            llm_provider="openai_compat",
            llm_base_url="http://x", llm_api_key="k", llm_model="m",
            gemini_api_key=None,
            hard_query_routing=True,
        )


def test_routing_flag_with_openai_compat_main_provider_is_valid():
    """The main provider being openai_compat must NOT block routing: prod runs
    Groq as main, and the hard provider only needs the gemini key."""
    from app.config import Settings

    s = Settings(
        _env_file=None,
        database_url="postgresql://fake:fake@localhost/fake",
        llm_provider="openai_compat",
        llm_base_url="http://x", llm_api_key="k", llm_model="m",
        gemini_api_key="gk",
        hard_query_routing=True,
    )
    assert s.hard_query_routing is True


def test_create_hard_provider_builds_its_own_client_for_openai_compat_main():
    """create_hard_provider must not depend on the main provider being Gemini:
    with llm_client=None (openai_compat main) it constructs its own genai
    client from the gemini key."""
    from unittest.mock import MagicMock, patch

    from app.rag.provider import GeminiProvider, create_hard_provider

    s = MagicMock()
    s.hard_query_routing = True
    s.gemini_api_key = "gk"
    s.hard_gemini_model = "gemini-3.5-flash"
    s.gemini_temperature = 0.1
    s.hard_timeout_s = 60.0
    s.hard_max_output_tokens = 8192

    fake_client = MagicMock()
    with patch("google.genai.Client", return_value=fake_client) as ctor:
        provider = create_hard_provider(s, llm_client=None)

    assert isinstance(provider, GeminiProvider)
    ctor.assert_called_once_with(api_key="gk")
    assert provider._client is fake_client


def test_create_hard_provider_reuses_the_main_gemini_client():
    from unittest.mock import MagicMock

    from app.rag.provider import GeminiProvider, create_hard_provider

    s = MagicMock()
    s.hard_query_routing = True
    s.gemini_api_key = "gk"
    s.hard_gemini_model = "gemini-3.5-flash"
    s.gemini_temperature = 0.1
    s.hard_timeout_s = 60.0
    s.hard_max_output_tokens = 8192

    main_client = MagicMock()
    provider = create_hard_provider(s, llm_client=main_client)

    assert isinstance(provider, GeminiProvider)
    assert provider._client is main_client


def test_create_hard_provider_returns_none_when_flag_off():
    from unittest.mock import MagicMock

    from app.rag.provider import create_hard_provider

    s = MagicMock()
    s.hard_query_routing = False
    assert create_hard_provider(s, llm_client=MagicMock()) is None


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def _make_chunk(section: str = "Some Rule", similarity: float = 0.9) -> Chunk:
    return Chunk(
        id="retrieved-1",
        content="380. Some rule text.",
        section=section,
        parent_section=None,
        source_type="rulebook",
        similarity=similarity,
    )


class _RecordingProvider:
    """LLM provider double that records what it was asked to generate from.

    Duck-typed rather than subclassing LLMProvider, so the ABC cannot enforce
    its shape here — when `model` was added, the other doubles failed at
    construction and this one failed inside the pipeline instead. Kept
    duck-typed (it records, it does not impersonate a real provider), but the
    lesson is why _NoHydeProvider inherits: see scripts/retrieval_probe.py.
    """

    def __init__(self, answer: str = "Reasoning:\n- r\nAnswer:\nRecorded answer.",
                 model: str = "recording-model") -> None:
        self.calls: list[dict] = []
        self._answer = answer
        self.model = model

    def generate(self, question, chunks, *, extra_system=""):
        self.calls.append({"question": question, "chunks": chunks, "extra_system": extra_system})
        return self._answer

    def hyde(self, question):
        return ""


def _fake_settings(routing_on: bool):
    s = MagicMock()
    s.corpus_version = "v1"
    s.top_k = 5
    s.top_k_fetch = 15
    s.rrf_k = 60
    s.gemini_temperature = 0.1
    s.gemini_timeout_s = 10.0
    s.prompt_version = "v6"
    s.cache_ttl_s = 86400
    s.enable_reranker = False
    s.reranker_model = "x"
    s.rerank_pool_size = 15
    s.keyword_family_extra = 0
    s.hard_query_routing = routing_on
    s.llm_model = None
    s.gemini_model = "gemini-flash-lite-latest"
    # MagicMock attrs are truthy by default — pin the Phase 2 flags to the real
    # Settings defaults (all off), or they silently enable features these tests
    # are not about (and, for concise_reasoning, change the cache key).
    s.semantic_cache_enabled = False
    s.skip_hyde_when_routed = False
    s.concise_reasoning = False
    # 3.11.1a. Without this the pipeline tests below run with relaxed
    # EFFECTIVELY ON (truthy MagicMock), so the branch's headline claim —
    # "flag off is byte-identical" — would be asserted in the one configuration
    # that does not test it.
    s.hard_routing_relaxed = False
    return s


# The classifier needs cards: the DB card vocabulary is unavailable under the
# fake pool, so hardness comes from explicit card_mentions (card_count=2).
_HARD_QUESTION = "Can Vex Apathetic stun Tideturner before its trigger resolves?"
_HARD_MENTIONS = ["Vex Apathetic", "Tideturner"]
_EASY_QUESTION = "How many cards do I draw at the start?"


def _run_pipeline(question, settings, provider, hard_provider, card_mentions=None):
    from tests.conftest import FakeEmbedder

    with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
        with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
            with patch("app.rag.pipeline.get_cached", return_value=None):
                with patch("app.rag.pipeline.set_cached"):
                    from app.rag.pipeline import answer_question
                    return answer_question(
                        question, FakeEmbedder(), MagicMock(), provider, settings,
                        card_mentions=card_mentions, hard_provider=hard_provider,
                    )


def test_flag_off_never_touches_the_hard_provider():
    provider = _RecordingProvider()
    hard = _RecordingProvider()

    _run_pipeline(_HARD_QUESTION, _fake_settings(routing_on=False), provider, hard, card_mentions=_HARD_MENTIONS)

    assert hard.calls == []
    assert len(provider.calls) == 1
    # Retrieved context, not stuffed.
    assert [c.id for c in provider.calls[0]["chunks"]] == ["retrieved-1"]


def test_flag_on_routes_hard_query_to_hard_provider_with_stuffed_context():
    from app.rag.routing import RULEBOOK_CHUNK_ID

    provider = _RecordingProvider()
    hard = _RecordingProvider()

    result = _run_pipeline(_HARD_QUESTION, _fake_settings(routing_on=True), provider, hard, card_mentions=_HARD_MENTIONS)

    assert len(hard.calls) == 1
    assert provider.calls == []  # generation went to the hard provider only
    stuffed = hard.calls[0]["chunks"]
    assert stuffed[-1].id == RULEBOOK_CHUNK_ID
    assert result.answer.strip().endswith("Recorded answer.")


def test_flag_on_easy_query_stays_on_the_normal_path():
    provider = _RecordingProvider()
    hard = _RecordingProvider()

    _run_pipeline(_EASY_QUESTION, _fake_settings(routing_on=True), provider, hard)

    assert hard.calls == []
    assert len(provider.calls) == 1


def test_flag_on_without_hard_provider_falls_back_to_normal_path():
    provider = _RecordingProvider()

    _run_pipeline(_HARD_QUESTION, _fake_settings(routing_on=True), provider, None, card_mentions=_HARD_MENTIONS)

    assert len(provider.calls) == 1
    assert [c.id for c in provider.calls[0]["chunks"]] == ["retrieved-1"]


def test_flag_on_stuffing_unavailable_falls_back_to_normal_path():
    provider = _RecordingProvider()
    hard = _RecordingProvider()

    with patch("app.rag.pipeline.build_stuffed_chunks", return_value=None):
        _run_pipeline(_HARD_QUESTION, _fake_settings(routing_on=True), provider, hard, card_mentions=_HARD_MENTIONS)

    assert hard.calls == []
    assert len(provider.calls) == 1


def test_cache_namespace_is_keyed_on_the_routing_flag():
    """A flag flip (either direction) must start cold instead of serving up to
    cache_ttl_s of answers produced by the other model/context. The routed bit
    itself can't be in the key (the cache lookup precedes retrieval, which the
    classifier needs), so the whole namespace is keyed on the FLAG — and with
    the flag off the key is byte-identical to pre-routing behaviour."""
    from tests.conftest import FakeEmbedder

    captured = {}

    def _capture(question, cv, mentions, pv):
        captured.setdefault("pvs", []).append(pv)
        return f"key-{pv}"

    provider = _RecordingProvider()
    for routing_on in (False, True):
        with patch("app.rag.pipeline.make_cache_key", side_effect=_capture):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
                    with patch("app.rag.pipeline.get_cached", return_value=None):
                        with patch("app.rag.pipeline.set_cached"):
                            from app.rag.pipeline import answer_question
                            answer_question(
                                _EASY_QUESTION, FakeEmbedder(), MagicMock(), provider,
                                _fake_settings(routing_on=routing_on),
                            )

    pv_off, pv_on = captured["pvs"]
    assert pv_off == "v6"          # flag off: pre-routing key, byte-identical
    assert pv_on == "v6+hard-routing"
    assert pv_off != pv_on


def test_routed_rulebook_citation_carries_no_rule_codes():
    """extract_rule_codes over the WHOLE rulebook would put thousands of codes
    in one citation (response bloat + paper-hit recall in the eval harness)."""
    from app.rag.routing import RULEBOOK_CHUNK_ID

    provider = _RecordingProvider()
    hard = _RecordingProvider()

    result = _run_pipeline(_HARD_QUESTION, _fake_settings(routing_on=True), provider, hard, card_mentions=_HARD_MENTIONS)

    rulebook_cites = [c for c in result.citations if c.chunk_id == RULEBOOK_CHUNK_ID]
    assert rulebook_cites, "routed response must cite the stuffed rulebook chunk"
    assert rulebook_cites[0].rule_codes == []
    assert len(rulebook_cites[0].content_preview) <= 200


def test_cache_namespace_is_keyed_on_the_relaxed_flag():
    """Same rule as the routing flag above, for the same reason.

    hard_routing_relaxed moves the (1 card, 1 keyword) cell into the routed
    bucket: those questions get a different CONTEXT (the stuffed rulebook) and a
    different MODEL (the thinking provider). That is a strictly larger delta
    than concise_reasoning, which already earns its own suffix. Without one, the
    two-step flip serves up to cache_ttl_s of pre-flip, non-routed answers for
    exactly the questions the flag exists to route — and the flip's own
    verification would be reading the old mode.
    """
    from tests.conftest import FakeEmbedder

    captured = {}

    def _capture(question, cv, mentions, pv):
        captured.setdefault("pvs", []).append(pv)
        return f"key-{pv}"

    provider = _RecordingProvider()
    for relaxed in (False, True):
        settings = _fake_settings(routing_on=True)
        settings.hard_routing_relaxed = relaxed
        with patch("app.rag.pipeline.make_cache_key", side_effect=_capture):
            with patch("app.rag.pipeline.hybrid_search", return_value=[_make_chunk()]):
                with patch("app.rag.pipeline.tagged_lookup", return_value=[]):
                    with patch("app.rag.pipeline.get_cached", return_value=None):
                        with patch("app.rag.pipeline.set_cached"):
                            from app.rag.pipeline import answer_question
                            answer_question(
                                _EASY_QUESTION, FakeEmbedder(), MagicMock(), provider,
                                settings,
                            )

    pv_off, pv_on = captured["pvs"]
    assert pv_off == "v6+hard-routing"   # relaxed off: key unchanged from 4.2/4.3
    assert pv_on == "v6+hard-routing+relaxed"
    assert pv_off != pv_on
