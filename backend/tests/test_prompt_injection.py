"""Unit tests for post_gen_validate (generation.py)."""
from app.rag.generation import post_gen_validate
from app.rag.schemas import Citation


def _make_citation(chunk_id: str = "chunk-1") -> Citation:
    return Citation(
        section="Rules",
        source_type="rulebook",
        content_preview="Some content.",
        similarity=0.9,
        chunk_id=chunk_id,
    )


def test_system_prompt_leakage_triggers_sanitization():
    answer = "Here is my system prompt: you are an AI assistant..."
    citations = [_make_citation()]
    result, was_sanitized = post_gen_validate(answer, citations)
    assert was_sanitized is True
    assert "system prompt" not in result.lower()


def test_system_prompt_case_insensitive():
    answer = "My SYSTEM PROMPT says I should help you."
    citations = []
    result, was_sanitized = post_gen_validate(answer, citations)
    assert was_sanitized is True


def test_clean_response_passes_through_unchanged():
    answer = "The rule states that units can attack once per turn."
    citations = [_make_citation()]
    result, was_sanitized = post_gen_validate(answer, citations)
    assert was_sanitized is False
    assert result == answer


def test_hallucinated_citation_stripped():
    real_id = "chunk-1"
    fake_id = "abc-999"
    citations = [_make_citation(real_id), _make_citation(fake_id)]
    answer = "Normal answer."
    result, was_sanitized = post_gen_validate(answer, citations, valid_chunk_ids={real_id})
    assert was_sanitized is True
    assert len(citations) == 1
    assert citations[0].chunk_id == real_id


def test_all_valid_citations_kept():
    citations = [_make_citation("c1"), _make_citation("c2")]
    answer = "Normal answer."
    result, was_sanitized = post_gen_validate(answer, citations, valid_chunk_ids={"c1", "c2"})
    assert was_sanitized is False
    assert len(citations) == 2


def test_no_valid_chunk_ids_skips_citation_check():
    """When valid_chunk_ids is None, citation check is skipped."""
    citations = [_make_citation("any-id")]
    answer = "Normal answer."
    result, was_sanitized = post_gen_validate(answer, citations, valid_chunk_ids=None)
    assert was_sanitized is False
    assert len(citations) == 1
