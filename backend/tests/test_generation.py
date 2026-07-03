"""Tests for the system instruction (build_prompt) and source_type-agnostic post_gen_validate."""
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
