"""Tests for the system instruction (build_prompt) and source_type-agnostic post_gen_validate."""
from app.rag.generation import _SYSTEM_INSTRUCTION, build_prompt, post_gen_validate
from app.rag.retrieval import Chunk
from app.rag.schemas import Citation


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
