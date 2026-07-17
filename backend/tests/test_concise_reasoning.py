"""Tests for concise reasoning on simple queries (improvement plan 2.6).

Rule 7 of the system prompt makes a Reasoning section mandatory. That is what
lifts the hard bucket — but on a direct one-rule lookup ("how many copies of a
card can I run?") it pays output tokens, the expensive side, to restate the
obvious.

2.6 CAPS the section on simple queries; it never removes it. Removing it would
undo the v6/v7 chaining few-shots and break the Reasoning:/Answer: parsing. The
tests below pin the three questions that decide whether this is safe:

  1. Does a hard/scaffolded query ever get the cap? (It must not.)
  2. Does a routed query ever get the cap? (It must not — it went to the
     thinking model precisely because it needs room to reason.)
  3. Can a concise answer and a verbose one collide in the cache? (They must
     not — the flag carries its own cache namespace.)
"""
from unittest.mock import MagicMock, patch

from tests.conftest import FakeEmbedder, FakeLLMProvider


class _SystemSpy(FakeLLMProvider):
    """Captures the extra_system actually handed to generate()."""

    def __init__(self):
        self.extra_system = None

    def generate(self, question, chunks, *, extra_system: str = "") -> str:
        self.extra_system = extra_system
        return "Reasoning:\n- rule\n\nAnswer:\nYes."


def _settings(*, concise: bool):
    from tests.test_pipeline import _fake_settings

    s = _fake_settings()
    s.concise_reasoning = concise
    s.semantic_cache_enabled = False
    s.skip_hyde_when_routed = False
    s.hard_query_routing = False
    return s


def _run(settings, question, card_tags=()):
    from app.rag.pipeline import _Entities, answer_question
    from app.rag.retrieval import Chunk

    chunk = Chunk(
        id="c1", content="Some rule text.", section="103. Deck",
        parent_section=None, source_type="rulebook", similarity=0.7,
    )
    provider = _SystemSpy()
    entities = _Entities(auto_card_tags=list(card_tags), ambiguous_champion_count=0)
    with (
        patch("app.rag.pipeline._detect_entities", return_value=entities),
        patch("app.rag.pipeline.hybrid_search", return_value=[chunk]),
        patch("app.rag.pipeline.tagged_lookup", return_value=[]),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        answer_question(question, FakeEmbedder(), MagicMock(), provider, settings)
    return provider.extra_system


_SIMPLE = "How many copies of the same card can I include in my main deck?"
_MULTI_CARD = "My opponent controls Vex Apathetic. I play Tideturner. What happens?"


def test_simple_query_gets_the_brevity_cap():
    from app.rag.generation import _CONCISE_REASONING

    assert _run(_settings(concise=True), _SIMPLE) == _CONCISE_REASONING


def test_flag_off_appends_nothing():
    """Byte-identical to pre-2.6 behaviour."""
    assert _run(_settings(concise=False), _SIMPLE) == ""


def test_multi_card_query_gets_the_scaffold_not_the_cap():
    """The scaffold wins: a question needing it is by definition not a simple
    lookup, so the two can never both be appended."""
    from app.rag.generation import _MULTI_CARD_SCAFFOLD

    out = _run(_settings(concise=True), _MULTI_CARD, card_tags=["vex apathetic", "tideturner"])
    assert out == _MULTI_CARD_SCAFFOLD


def test_conditional_language_query_gets_the_scaffold_not_the_cap():
    """needs_scaffold also fires on conditional/simultaneous timing language,
    with zero cards. That question is not simple either."""
    from app.rag.generation import _MULTI_CARD_SCAFFOLD

    q = "If both triggers happen simultaneously, which one resolves first?"
    assert _run(_settings(concise=True), q) == _MULTI_CARD_SCAFFOLD


def test_routed_query_never_gets_the_cap():
    """A routed query reached the thinking model BECAUSE it needs room to
    reason. Capping it would defeat the whole point of 4.2+4.3."""
    from app.rag.pipeline import _Entities, answer_question
    from app.rag.retrieval import Chunk

    s = _settings(concise=True)
    s.hard_query_routing = True
    s.hard_gemini_model = "gemini-3.5-flash"

    chunk = Chunk(
        id="c1", content="rule", section="103. Deck", parent_section=None,
        source_type="rulebook", similarity=0.7,
    )
    hard = _SystemSpy()
    entities = _Entities(auto_card_tags=["vex apathetic", "tideturner"], ambiguous_champion_count=0)
    with (
        patch("app.rag.pipeline._detect_entities", return_value=entities),
        patch("app.rag.pipeline.hybrid_search", return_value=[chunk]),
        patch("app.rag.pipeline.tagged_lookup", return_value=[]),
        patch("app.rag.pipeline.get_cached", return_value=None),
        patch("app.rag.pipeline.set_cached"),
    ):
        answer_question(
            _MULTI_CARD, FakeEmbedder(), MagicMock(), FakeLLMProvider(), s,
            hard_provider=hard,
        )
    # It routed (the hard provider generated) and got the scaffold — never the cap.
    from app.rag.generation import _CONCISE_REASONING

    assert hard.extra_system != _CONCISE_REASONING


# ---------------------------------------------------------------------------
# Cache coherence — a concise answer must never be served as a verbose one
# ---------------------------------------------------------------------------

def _captured_key(settings) -> str:
    from app.rag.pipeline import _Entities, answer_question

    entities = _Entities(auto_card_tags=[], ambiguous_champion_count=0)
    with (
        patch("app.rag.pipeline._detect_entities", return_value=entities),
        patch("app.rag.pipeline.hybrid_search", return_value=[]),
        patch("app.rag.pipeline.tagged_lookup", return_value=[]),
        patch("app.rag.pipeline.get_cached", return_value=None) as gc,
        patch("app.rag.pipeline.set_cached"),
    ):
        answer_question(_SIMPLE, FakeEmbedder(), MagicMock(), FakeLLMProvider(), settings)
    return gc.call_args[0][0]


def test_concise_and_verbose_answers_use_different_cache_keys():
    assert _captured_key(_settings(concise=True)) != _captured_key(_settings(concise=False))
