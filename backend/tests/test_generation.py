"""Tests for the system instruction (build_prompt) and source_type-agnostic post_gen_validate."""
import pytest

from app.rag.generation import (
    _SAFE_FALLBACK,
    _SYSTEM_INSTRUCTION,
    _call_gemini,
    build_prompt,
    post_gen_validate,
    strip_citation_markers,
)
from app.rag.retrieval import Chunk
from app.rag.schemas import Citation


class _FakeResponse:
    """Stand-in for a google-genai response whose .text may be None or raise."""

    def __init__(self, text=None, raises=False):
        self._text = text
        self._raises = raises

    @property
    def text(self):
        if self._raises:
            raise ValueError("no candidates / safety blocked")
        return self._text


class _FakeGeminiClient:
    def __init__(self, response):
        self._response = response

        class _Models:
            def generate_content(_self, **_kwargs):
                return response

        self.models = _Models()


def _chunk(source_type: str, section: str = "Yasuo", chunk_id: str = "c1") -> Chunk:
    return Chunk(
        id=chunk_id,
        content=f"Sample content for {section}.",
        section=section,
        parent_section=None,
        source_type=source_type,
        similarity=0.9,
    )


def _citation(chunk_id: str, source_type: str = "card") -> Citation:
    return Citation(
        section="Yasuo",
        source_type=source_type,
        content_preview="x",
        similarity=0.9,
        chunk_id=chunk_id,
    )


# ---------------------------------------------------------------------------
# Authority chain — errata supersedes the base rule
#
# The product's pitch is "a judge that knows errata and patch notes". The prompt
# must declare the authority chain, not merely mention that a rule "comes from
# errata". When sources conflict, the errata wins.
# ---------------------------------------------------------------------------

def test_prompt_declares_errata_supersedes_base_rule():
    text = _SYSTEM_INSTRUCTION.lower()
    assert "errata" in text
    assert "supersede" in text or "supersedes" in text or "overrides" in text or "takes precedence" in text


def test_prompt_declares_conflict_resolution_order():
    """When sources conflict the prompt must instruct applying the errata/patch over the base rule."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "conflict" in text
    assert "patch" in text  # patch notes named in the authority chain


# ---------------------------------------------------------------------------
# Rule 6 — extended to make card text authoritative
# ---------------------------------------------------------------------------

def test_rule_6_mentions_card_text_as_authoritative():
    """Rule 6 must signal that printed card text is authoritative for that card's behavior."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "card text" in text
    assert "authoritative" in text


def test_rule_6_still_requires_logical_chain():
    """Rule 6's original chain-of-reasoning intent must survive the card extension."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "chain" in text  # rule 6 still talks about chaining
    assert "logical" in text or "inference" in text or "infer" in text


# ---------------------------------------------------------------------------
# Rule 7 — new: enumerate chain steps + declare ambiguity
# ---------------------------------------------------------------------------

def test_rule_7_exists():
    """A 7th numbered rule must be present in the system instruction."""
    assert "\n7." in _SYSTEM_INSTRUCTION


def test_rule_7_requires_enumerating_chain_steps():
    """Multi-step chains must enumerate each link with its justification."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "list every rule" in text or "each link" in text or "each step" in text
    assert "why each is relevant" in text


def test_rule_7_handles_ambiguity_explicitly():
    """When card text + rules leave more than one resolution, the LLM must declare ambiguity."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "ambiguous" in text or "ambiguity" in text


def test_rule_7_forbids_picking_to_sound_confident():
    """Rule 7 must forbid arbitrarily picking one outcome to sound confident."""
    text = _SYSTEM_INSTRUCTION.lower()
    # Accept a few natural phrasings.
    assert any(p in text for p in ("sound confident", "appear confident", "to sound certain"))


# ---------------------------------------------------------------------------
# Worked examples (improvement plan 4.1) — rule 6 DESCRIBED chaining but never
# SHOWED it. The prod Deflect-in-trash query retrieved the right rules
# (809 + 365.1) and still declared ambiguity instead of chaining them.
# ---------------------------------------------------------------------------

def test_prompt_contains_worked_examples():
    """At least two complete Reasoning/Answer examples must be present."""
    assert "Example 1" in _SYSTEM_INSTRUCTION
    assert "Example 2" in _SYSTEM_INSTRUCTION
    # Each example is a COMPLETE worked answer, not a one-liner: the format
    # headings must appear beyond rule 7's format template (2 examples + template).
    assert _SYSTEM_INSTRUCTION.count("Reasoning:") >= 3
    assert _SYSTEM_INSTRUCTION.count("Answer:") >= 3


def test_worked_examples_are_not_citable_context():
    """The examples must warn the model not to source its answer from them."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "may not be in your context" in text
    assert "never cite them" in text


def test_worked_examples_push_conclusion_over_ambiguity():
    """The Deflect example exists to fix 'retrieves right rules, refuses to
    conclude' — the prompt must say a resolved chain means committing."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "do not declare ambiguity" in text
    assert "commit to the conclusion" in text


def test_worked_example_deflect_chains_zone_rule():
    """Example 2 mirrors the prod failure: Deflect (809) chained with the
    passive-abilities-on-Board rule (365.1)."""
    assert "809.1" in _SYSTEM_INSTRUCTION
    assert "365.1" in _SYSTEM_INSTRUCTION
    text = _SYSTEM_INSTRUCTION.lower()
    assert "deflect" in text
    assert "trash" in text


# ---------------------------------------------------------------------------
# Rule 2 — must remain intact (anti-hallucination of card names)
# ---------------------------------------------------------------------------

def test_rule_2_still_forbids_inventing_card_names():
    """Rule 2 is the main guard against inventing nonexistent cards — must survive Phase 2."""
    text = _SYSTEM_INSTRUCTION.lower()
    assert "do not invent" in text or "not invent" in text
    assert "card name" in text or "card names" in text


# ---------------------------------------------------------------------------
# build_prompt with card chunks
# ---------------------------------------------------------------------------

def test_build_prompt_includes_card_source_type_in_context_block():
    """When a card chunk is part of the context, source: card must appear in the prompt."""
    prompt = build_prompt("Can Yasuo attack the turn it enters?", [_chunk("card")])
    assert "source: card" in prompt


def test_build_prompt_preserves_existing_chunk_layout_with_card_chunks():
    """Card chunks must not break the [#N] citation contract."""
    chunks = [_chunk("card", section="Yasuo", chunk_id="c1"),
              _chunk("rulebook", section="Attacking 401.1", chunk_id="c2")]
    prompt = build_prompt("question?", chunks)
    assert "[#1]" in prompt
    assert "[#2]" in prompt


# ---------------------------------------------------------------------------
# post_gen_validate — transparent to card source_type
# ---------------------------------------------------------------------------

def test_post_gen_validate_strips_hallucinated_card_citations():
    """Hallucinated chunk_ids must be stripped even when source_type is 'card'."""
    real, fake = "card-1", "card-fake"
    citations = [_citation(real, "card"), _citation(fake, "card")]
    result, was_sanitized = post_gen_validate(
        "Yasuo cannot attack the turn it enters.",
        citations,
        valid_chunk_ids={real},
    )
    assert was_sanitized is True
    assert len(citations) == 1
    assert citations[0].chunk_id == real


def test_post_gen_validate_keeps_valid_card_citations_untouched():
    """Citations matching real card chunk_ids must pass through unchanged."""
    citations = [_citation("card-1", "card"), _citation("rb-1", "rulebook")]
    result, was_sanitized = post_gen_validate(
        "Some answer about a card.",
        citations,
        valid_chunk_ids={"card-1", "rb-1"},
    )
    assert was_sanitized is False
    assert len(citations) == 2


# ---------------------------------------------------------------------------
# strip_citation_markers — removes the [#N] scaffolding from the display text.
# The SOURCES panel is built from chunks (pipeline), never parsed from these
# markers, so they are pure noise for the reader and must not survive to the UI.
# ---------------------------------------------------------------------------

def test_strip_citation_markers_single():
    assert strip_citation_markers("Yasuo cannot attack [#1].") == "Yasuo cannot attack."


def test_strip_citation_markers_grouped():
    assert strip_citation_markers("Both rules apply [#1, #2, #3].") == "Both rules apply."


def test_strip_citation_markers_adjacent():
    assert strip_citation_markers("It is exhausted [#1][#2] on entry.") == "It is exhausted on entry."


def test_strip_citation_markers_no_hash():
    assert strip_citation_markers("See the rule [1, 2].") == "See the rule."


def test_strip_citation_markers_midsentence_keeps_one_space():
    assert strip_citation_markers("The unit [#2] cannot attack.") == "The unit cannot attack."


def test_strip_citation_markers_leaves_plain_text_untouched():
    text = "Yasuo enters exhausted and cannot attack that turn."
    assert strip_citation_markers(text) == text


# ---------------------------------------------------------------------------
# _call_gemini — a response with no usable text must not crash the pipeline
#
# A safety block / empty candidates yields response.text == None (or raises on
# access). Letting that propagate crashes post_gen_validate (answer.lower()) and
# surfaces as a raw 500. We return a controlled fallback instead.
# ---------------------------------------------------------------------------

def test_call_gemini_returns_fallback_when_text_is_none():
    client = _FakeGeminiClient(_FakeResponse(text=None))
    result = _call_gemini(client, "gemini-2.0-flash", "prompt", timeout_s=1.0)
    assert result == _SAFE_FALLBACK


def test_call_gemini_returns_fallback_when_text_accessor_raises():
    client = _FakeGeminiClient(_FakeResponse(raises=True))
    result = _call_gemini(client, "gemini-2.0-flash", "prompt", timeout_s=1.0)
    assert result == _SAFE_FALLBACK


def test_call_gemini_returns_text_on_normal_response():
    client = _FakeGeminiClient(_FakeResponse(text="Yasuo cannot attack."))
    result = _call_gemini(client, "gemini-2.0-flash", "prompt", timeout_s=1.0)
    assert result == "Yasuo cannot attack."


# ---------------------------------------------------------------------------
# has_empty_answer_section — the empty "Answer:" guard
#
# On ambiguous questions Gemini sometimes writes a full Reasoning block and then
# stops right after "Answer:", leaving no conclusion. response.text is non-empty
# (it carries the reasoning) so it slips past the None guard and reaches the UI
# as a blank bubble. This detector lets the pipeline retry / fall back.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# _hyde_gemini — single-shot HyDE arm for GeminiProvider (PR1, hard-bucket-v2)
#
# Best-effort passage for the retrieval HyDE arm. Never raises (degrades to
# raw-only retrieval on any failure) and never retries (protects the answer
# generation's quota budget — see design D1).
# ---------------------------------------------------------------------------


class _RecordingGeminiClient:
    """Fake genai client that records every generate_content call's kwargs."""

    def __init__(self, response=None, exc: Exception | None = None):
        self.calls: list[dict] = []
        outer = self

        class _Models:
            def generate_content(_self, **kwargs):
                outer.calls.append(kwargs)
                if exc is not None:
                    raise exc
                return response

        self.models = _Models()


def test_hyde_gemini_happy_path_returns_text():
    from app.rag.generation import _hyde_gemini

    client = _RecordingGeminiClient(
        response=_FakeResponse(text="Accelerate lets you play a card early by paying its cost.")
    )
    result = _hyde_gemini(client, "gemini-2.0-flash", "How does Accelerate work?", timeout_s=5.0)
    assert result == "Accelerate lets you play a card early by paying its cost."


def test_hyde_gemini_returns_empty_on_exception():
    from app.rag.generation import _hyde_gemini

    client = _RecordingGeminiClient(exc=RuntimeError("network error"))
    result = _hyde_gemini(client, "gemini-2.0-flash", "How does Accelerate work?", timeout_s=5.0)
    assert result == ""


def test_hyde_gemini_returns_empty_when_text_is_none():
    from app.rag.generation import _hyde_gemini

    client = _RecordingGeminiClient(response=_FakeResponse(text=None))
    result = _hyde_gemini(client, "gemini-2.0-flash", "q?", timeout_s=5.0)
    assert result == ""


def test_hyde_gemini_is_single_shot_no_retry_on_429(monkeypatch):
    """A simulated 429 must NOT be retried — HyDE is best-effort and must not
    burn the shared quota budget that _completion_with_retry protects for the
    answer generation call."""
    from app.rag import generation
    from app.rag.generation import _hyde_gemini

    class _RateLimitError(Exception):
        status_code = 429

    client = _RecordingGeminiClient(exc=_RateLimitError("429 rate limited"))
    slept: list[float] = []
    monkeypatch.setattr(generation.time, "sleep", lambda s: slept.append(s))

    result = _hyde_gemini(client, "gemini-2.0-flash", "q?", timeout_s=5.0)

    assert result == ""
    assert len(client.calls) == 1, "must call generate_content exactly once — no retry"
    assert slept == [], "no backoff sleep must occur — single-shot, not via _completion_with_retry"


def test_hyde_gemini_uses_hyde_prompt_verbatim():
    from app.rag.generation import _HYDE_PROMPT, _hyde_gemini

    client = _RecordingGeminiClient(response=_FakeResponse(text="answer"))
    _hyde_gemini(client, "gemini-2.0-flash", "How does Accelerate work?", timeout_s=5.0)

    assert client.calls[0]["contents"] == _HYDE_PROMPT.format(question="How does Accelerate work?")


def test_hyde_gemini_config_parity():
    """max_output_tokens~160 and temperature=0.0 mirror the openai-compat HyDE
    arm; timeout defaults to 10.0s — the Gemini API rejects manual deadlines
    under 10s with 400 INVALID_ARGUMENT ("Minimum allowed deadline is 10s"),
    which the never-raise contract would swallow, silently disabling the HyDE
    arm on every call. Still well under the 30s generation timeout."""
    from app.rag.generation import _hyde_gemini

    client = _RecordingGeminiClient(response=_FakeResponse(text="answer"))
    _hyde_gemini(client, "gemini-2.0-flash", "q?")

    config = client.calls[0]["config"]
    assert config.max_output_tokens == 160
    assert config.temperature == 0.0
    assert config.http_options.timeout == 10000, "timeout_s default 10.0 -> 10000ms, the API's minimum manual deadline"


from app.rag.generation import has_empty_answer_section


def test_empty_answer_section_detected_when_nothing_follows_heading():
    text = "Reasoning:\n- Rule 461.3.d: no result if both have units.\n\nAnswer:"
    assert has_empty_answer_section(text) is True


def test_empty_answer_section_detected_with_trailing_whitespace_and_markers():
    text = "Reasoning:\n- Some rule applies.\nAnswer:  \n\n  [#1]  "
    assert has_empty_answer_section(text) is True


def test_empty_answer_section_detected_with_markdown_bold_heading():
    text = "Reasoning:\n- Some rule.\n\n**Answer:**\n"
    assert has_empty_answer_section(text) is True


def test_answer_section_with_content_is_not_empty():
    text = "Reasoning:\n- Rule 301.\n\nAnswer: Yes, you can block with it."
    assert has_empty_answer_section(text) is False


def test_plain_response_without_heading_is_not_empty():
    # The no-info fallback has no "Answer:" heading — it is a real answer, not blank.
    assert has_empty_answer_section(_NO_INFO_ANSWER_TEXT) is False


def test_answer_word_inside_reasoning_prose_does_not_count():
    # "answer:" mid-sentence in reasoning must not be mistaken for the heading.
    text = "Reasoning:\n- The obvious answer: it depends on priority.\n\nAnswer: It depends."
    assert has_empty_answer_section(text) is False


_NO_INFO_ANSWER_TEXT = (
    "I don't have enough information to answer that question with the available rules."
)


# ---------------------------------------------------------------------------
# needs_scaffold — multi-card interaction detection (PR3, hard-bucket-v2)
#
# Pure function: True when 2+ distinct cards are involved, OR the question
# uses conditional/simultaneous language (case-insensitive). Otherwise False.
# ---------------------------------------------------------------------------

def test_needs_scaffold_true_when_two_or_more_cards():
    from app.rag.generation import needs_scaffold
    assert needs_scaffold("What happens when they interact?", 2) is True


def test_needs_scaffold_true_with_many_cards():
    from app.rag.generation import needs_scaffold
    assert needs_scaffold("Resolve this board state.", 5) is True


def test_needs_scaffold_false_with_zero_cards_and_no_conditional_language():
    from app.rag.generation import needs_scaffold
    assert needs_scaffold("What does Accelerate do?", 0) is False


def test_needs_scaffold_false_with_one_card_and_no_conditional_language():
    from app.rag.generation import needs_scaffold
    assert needs_scaffold("What does Yasuo's ability do?", 1) is False


@pytest.mark.parametrize(
    "phrase",
    [
        "if it is exhausted, then it cannot attack",
        "does this trigger simultaneously with the other one",
        "at the same time as the attack",
        "whenever both units are ready",
        "whenever it enters the board",
    ],
)
def test_needs_scaffold_true_on_conditional_language_zero_cards(phrase):
    from app.rag.generation import needs_scaffold
    assert needs_scaffold(phrase, 0) is True


def test_needs_scaffold_true_on_conditional_language_one_card():
    from app.rag.generation import needs_scaffold
    assert needs_scaffold("If Yasuo attacks, then what happens?", 1) is True


def test_needs_scaffold_conditional_language_is_case_insensitive():
    from app.rag.generation import needs_scaffold
    assert needs_scaffold("IF it is exhausted, THEN it cannot attack", 0) is True
    assert needs_scaffold("SIMULTANEOUSLY resolving both triggers", 0) is True


# ---------------------------------------------------------------------------
# build_prompt(extra_system=...) — scaffold-augmented prompt (PR3, hard-bucket-v2)
# ---------------------------------------------------------------------------

def test_build_prompt_default_extra_system_is_backward_compatible():
    from app.rag.generation import build_prompt
    chunks = [_make_generation_chunk()]
    old_style = build_prompt("How does Accelerate work?", chunks)
    new_style = build_prompt("How does Accelerate work?", chunks, extra_system="")
    assert old_style == new_style


def test_build_prompt_with_scaffold_contains_scaffold_instructions():
    from app.rag.generation import _MULTI_CARD_SCAFFOLD, build_prompt
    chunks = [_make_generation_chunk()]
    prompt = build_prompt("If Yasuo attacks, what happens?", chunks, extra_system=_MULTI_CARD_SCAFFOLD)
    assert _MULTI_CARD_SCAFFOLD in prompt


def test_build_prompt_with_scaffold_preserves_security_rules_and_citation_format():
    from app.rag.generation import _MULTI_CARD_SCAFFOLD, build_prompt
    chunks = [_make_generation_chunk()]
    prompt = build_prompt("If Yasuo attacks, what happens?", chunks, extra_system=_MULTI_CARD_SCAFFOLD)
    assert "Security rules (non-negotiable):" in prompt
    assert "[#1]" in prompt


def test_build_prompt_with_scaffold_has_no_bare_answer_heading_of_its_own():
    """The scaffold text itself must not contain a line-anchored 'Answer:'
    heading — it would confuse _ANSWER_HEADING_RE's 'last heading' logic."""
    from app.rag.generation import _ANSWER_HEADING_RE, _MULTI_CARD_SCAFFOLD
    assert _ANSWER_HEADING_RE.search(_MULTI_CARD_SCAFFOLD) is None


def _make_generation_chunk():
    return Chunk(
        id="gen-chunk-1",
        content="Some content about the rules.",
        section="Test Section",
        parent_section=None,
        source_type="rulebook",
        similarity=0.9,
    )
