"""Tests for the two HyDE cost levers (improvement plan 2.1 + 2.2).

Context — the plan's ORIGINAL 2.1 ("run the raw arm first; if its best cosine
clears a threshold, skip HyDE") was killed by measurement, not by taste. On the
eval set the raw best cosine does not separate a retrieval that found the gold
rule from one that missed it:

    eval-037  cosine 0.7007 (2nd highest of all)  -> gold NOT in the top 15
    eval-010  cosine 0.5277 (the LOWEST)          -> gold at rank 1

Every threshold >= 0.75 (the plan's own suggestion) skips HyDE on 0/40
questions — zero savings. Every threshold low enough to save calls strips HyDE
from precisely the hard questions that need it (eval-015/017/026/030/037 all sit
in that band). There is no defensible cut.

What DOES save a call, for free: a routed query replaces its retrieved context
with the stuffed rulebook (`chunks = stuffed`), so the HyDE arm it just paid for
is discarded. Don't build it.
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FakeEmbedder, FakeLLMProvider


class _HydeSpy(FakeLLMProvider):
    """Records whether the (LLM-costing) HyDE call was made."""

    def __init__(self):
        self.hyde_calls = 0

    def hyde(self, question: str) -> str:
        self.hyde_calls += 1
        return "a hypothetical answer"


def _settings(*, skip_when_routed: bool, routing: bool = True):
    from tests.test_pipeline import _fake_settings

    s = _fake_settings()
    s.skip_hyde_when_routed = skip_when_routed
    s.hard_query_routing = routing
    s.hard_gemini_model = "gemini-3.5-flash"
    return s


def _entities(card_tags):
    from app.rag.pipeline import _Entities

    return _Entities(auto_card_tags=list(card_tags), ambiguous_champion_count=0)


def _run(settings, card_tags, *, hard_provider=None):
    from app.rag.pipeline import answer_question

    provider = _HydeSpy()
    with (
        patch("app.rag.pipeline._detect_entities", return_value=_entities(card_tags)),
        patch("app.rag.pipeline.hybrid_search", return_value=[]),
        patch("app.rag.pipeline.tagged_lookup", return_value=[]),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        answer_question(
            "My opponent controls Vex Apathetic. I play Tideturner. What happens?",
            FakeEmbedder(), MagicMock(), provider, settings,
            hard_provider=hard_provider,
        )
    return provider


# ---------------------------------------------------------------------------
# 2.1 — skip HyDE when the query will be routed
# ---------------------------------------------------------------------------

def test_routed_query_does_not_pay_for_hyde():
    """Two cards -> hard -> routed -> its retrieval is thrown away. No HyDE call."""
    provider = _run(
        _settings(skip_when_routed=True),
        ["vex apathetic", "tideturner"],
        hard_provider=FakeLLMProvider(),
    )
    assert provider.hyde_calls == 0


def test_non_routed_query_still_pays_for_hyde():
    """The HyDE arm genuinely lifts recall on the normal path (fuse_eq: 41%->59%).
    Only the routed path may skip it."""
    provider = _run(
        _settings(skip_when_routed=True), [], hard_provider=FakeLLMProvider()
    )
    assert provider.hyde_calls == 1


def test_flag_off_pays_for_hyde_even_when_routed():
    """Byte-identical to pre-2.1 behaviour with the flag off."""
    provider = _run(
        _settings(skip_when_routed=False),
        ["vex apathetic", "tideturner"],
        hard_provider=FakeLLMProvider(),
    )
    assert provider.hyde_calls == 1


def test_no_hard_provider_means_no_routing_so_hyde_still_runs():
    """Routing can't happen without a hard provider, so the retrieval is NOT
    discarded — HyDE must still build the arm that will actually be used."""
    provider = _run(
        _settings(skip_when_routed=True),
        ["vex apathetic", "tideturner"],
        hard_provider=None,
    )
    assert provider.hyde_calls == 1


def test_routing_flag_off_means_hyde_still_runs():
    provider = _run(
        _settings(skip_when_routed=True, routing=False),
        ["vex apathetic", "tideturner"],
        hard_provider=FakeLLMProvider(),
    )
    assert provider.hyde_calls == 1


# ---------------------------------------------------------------------------
# 2.2 — a cheaper model for the throwaway HyDE passage
# ---------------------------------------------------------------------------

def test_hyde_uses_the_dedicated_model_when_set():
    from app.rag.provider import GeminiProvider

    p = GeminiProvider(
        client=MagicMock(), model="big-answer-model", temperature=0.1, timeout_s=10.0,
        hyde_model="small-cheap-model",
    )
    with patch("app.rag.generation._hyde_gemini", return_value="x") as h:
        p.hyde("a question")
    assert h.call_args[0][1] == "small-cheap-model"


def test_hyde_falls_back_to_the_main_model_when_unset():
    """Byte-identical to pre-2.2 behaviour when hyde_model is None."""
    from app.rag.provider import GeminiProvider

    p = GeminiProvider(
        client=MagicMock(), model="big-answer-model", temperature=0.1, timeout_s=10.0,
    )
    with patch("app.rag.generation._hyde_gemini", return_value="x") as h:
        p.hyde("a question")
    assert h.call_args[0][1] == "big-answer-model"


def test_openai_compat_hyde_uses_the_dedicated_model():
    from app.rag.provider import OpenAICompatProvider

    p = OpenAICompatProvider(
        base_url="http://x", api_key="k", model="big", temperature=0.1, timeout_s=10.0,
        hyde_model="small",
    )
    with patch("app.rag.generation._hyde_openai_compat", return_value="x") as h:
        p.hyde("a question")
    assert h.call_args.kwargs["model"] == "small"


def test_generation_still_uses_the_main_model_not_the_hyde_one():
    """The cheap model must never leak into the ANSWER path."""
    from app.rag.provider import GeminiProvider

    p = GeminiProvider(
        client=MagicMock(), model="big-answer-model", temperature=0.1, timeout_s=10.0,
        hyde_model="small-cheap-model",
    )
    with patch("app.rag.generation._call_gemini", return_value="ans") as g:
        p.generate("q", [])
    assert g.call_args[0][1] == "big-answer-model"
