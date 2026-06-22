"""Unit tests for eval_judge: verdict parser, provider selection, matcher, aggregation."""
import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.eval_judge import (
    aggregate_by_difficulty,
    compute_recall,
    match_rule_reference,
    parse_verdict,
)
from app.rag.schemas import Citation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _citation(
    section: str,
    source_type: str = "rulebook",
    content_preview: str = "",
    rule_codes: list[str] | None = None,
) -> Citation:
    return Citation(
        section=section,
        source_type=source_type,
        content_preview=content_preview,
        similarity=0.9,
        rule_codes=rule_codes or [],
    )


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------

def test_parse_verdict_clean_json():
    raw = '{"verdict": "correct", "justification": "Matches exactly."}'
    result = parse_verdict(raw)
    assert result["verdict"] == "correct"
    assert result["justification"] == "Matches exactly."


def test_parse_verdict_partial():
    raw = '{"verdict": "partial", "justification": "Missing detail."}'
    assert parse_verdict(raw)["verdict"] == "partial"


def test_parse_verdict_wrong():
    raw = '{"verdict": "wrong", "justification": "Contradicts the rule."}'
    assert parse_verdict(raw)["verdict"] == "wrong"


def test_parse_verdict_json_with_surrounding_text():
    raw = 'Here is my evaluation:\n{"verdict": "correct", "justification": "Accurate."}\nDone.'
    result = parse_verdict(raw)
    assert result["verdict"] == "correct"


def test_parse_verdict_invalid_json_returns_error():
    result = parse_verdict("I think it is correct maybe??")
    assert result["verdict"] == "error"


def test_parse_verdict_empty_string_returns_error():
    result = parse_verdict("")
    assert result["verdict"] == "error"


def test_parse_verdict_unknown_verdict_returns_error():
    raw = '{"verdict": "maybe", "justification": "Not sure."}'
    result = parse_verdict(raw)
    assert result["verdict"] == "error"


def test_parse_verdict_justification_truncated_at_500_chars():
    long = "x" * 600
    raw = json.dumps({"verdict": "correct", "justification": long})
    result = parse_verdict(raw)
    assert len(result["justification"]) <= 500


# ---------------------------------------------------------------------------
# judge_answer — provider selection
# ---------------------------------------------------------------------------

def test_judge_answer_uses_openai_compat_when_env_set():
    from scripts.eval_judge import judge_answer

    mock_raw = '{"verdict": "correct", "justification": "Spot on."}'

    with (
        patch("scripts.eval_judge._get_judge_config", return_value={"base_url": "http://x", "api_key": "k", "model": "m"}),
        patch("scripts.eval_judge._judge_openai_compat", return_value=mock_raw) as mock_compat,
        patch("scripts.eval_judge._judge_gemini") as mock_gemini,
    ):
        result = judge_answer("Q?", "Canonical.", "Generated.")
        mock_compat.assert_called_once()
        mock_gemini.assert_not_called()
        assert result["verdict"] == "correct"


def test_judge_answer_falls_back_to_gemini_when_no_env():
    from scripts.eval_judge import judge_answer

    mock_raw = '{"verdict": "partial", "justification": "Close but incomplete."}'

    with (
        patch("scripts.eval_judge._get_judge_config", return_value=None),
        patch("scripts.eval_judge._judge_gemini", return_value=mock_raw) as mock_gemini,
        patch("scripts.eval_judge._judge_openai_compat") as mock_compat,
    ):
        result = judge_answer("Q?", "Canonical.", "Generated.")
        mock_gemini.assert_called_once()
        mock_compat.assert_not_called()
        assert result["verdict"] == "partial"


def test_judge_answer_returns_error_verdict_on_exception():
    from scripts.eval_judge import judge_answer

    with (
        patch("scripts.eval_judge._get_judge_config", return_value=None),
        patch("scripts.eval_judge._judge_gemini", side_effect=RuntimeError("API down")),
    ):
        result = judge_answer("Q?", "Canonical.", "Generated.")
        assert result["verdict"] == "error"
        assert "API down" in result["justification"]


# ---------------------------------------------------------------------------
# match_rule_reference
# ---------------------------------------------------------------------------

def test_match_null_ref_returns_false():
    assert match_rule_reference(None, [_citation("103. Responsibility:")]) is False


def test_match_numeric_prefix_hit():
    # 103.2.b → top-level prefix 103 → section '103.' matches
    citations = [_citation("103. Responsibility:")]
    assert match_rule_reference("103.2.b", citations) is True


def test_match_numeric_prefix_miss():
    citations = [_citation("200. Some Other Rule")]
    assert match_rule_reference("103.2.b", citations) is False


def test_match_content_preview_hit():
    # The full ref appears in content_preview
    citations = [_citation("200.", content_preview="See rule 103.2.b for details on deck size.")]
    assert match_rule_reference("103.2.b", citations) is True


def test_match_content_sub_prefix_hit():
    # Sub-prefix (103.2) without terminal letter appears in content_preview
    citations = [_citation("200.", content_preview="Rule 103.2 limits copies to 3.")]
    assert match_rule_reference("103.2.b", citations) is True


def test_match_errata_path_hit():
    citations = [_citation("Dark Child", source_type="errata")]
    assert match_rule_reference("errata/origins/dark-child-starter", citations) is True


def test_match_errata_path_miss_no_errata_citation():
    citations = [_citation("103.", source_type="rulebook")]
    assert match_rule_reference("errata/origins/dark-child-starter", citations) is False


def test_match_multi_ref_one_hits():
    # '383.4.e, 459.2.d' — only 383 is present in citations
    citations = [_citation("383.")]
    assert match_rule_reference("383.4.e, 459.2.d", citations) is True


def test_match_multi_ref_none_hit():
    citations = [_citation("100. Introduction")]
    assert match_rule_reference("383.4.e, 459.2.d", citations) is False


def test_match_short_numeric_ref():
    # refs like '002', '166' — check section prefix
    citations = [_citation("166.")]
    assert match_rule_reference("166", citations) is True


def test_match_empty_citations():
    assert match_rule_reference("103.2.b", []) is False


def test_match_via_rule_codes_when_section_and_preview_miss():
    # The retriever returned the CORRECT chunk (it covers rule 143.4), but the
    # section header is a coarser number (140) and 143.4 lives beyond the 200-char
    # preview. Only rule_codes carries the truth. Before the fix this was a false
    # negative — recall was undercounted whenever the rule code wasn't the section
    # number and wasn't in the first 200 chars.
    cit = _citation(
        section="140. Units",
        content_preview="### 140. Units\n140. A unit is a game object on the board...",
        rule_codes=["140", "143", "143.4"],
    )
    assert match_rule_reference("143.4", [cit]) is True


def test_match_via_rule_codes_parent_covers_subrule():
    # ref is more specific than what the chunk lists: chunk has 103.2, ref is 103.2.b
    cit = _citation(section="101. Deck Construction", rule_codes=["101", "103", "103.2"])
    assert match_rule_reference("103.2.b", [cit]) is True


def test_match_rule_codes_unrelated_lineage_miss():
    cit = _citation(section="200. Other", rule_codes=["200", "201", "201.3"])
    assert match_rule_reference("143.4", [cit]) is False


# ---------------------------------------------------------------------------
# compute_recall
# ---------------------------------------------------------------------------

def test_compute_recall_basic():
    results = [
        {"has_ref": True, "retrieval_hit": True},
        {"has_ref": True, "retrieval_hit": False},
        {"has_ref": False, "retrieval_hit": False},
        {"has_ref": True, "retrieval_hit": True},
    ]
    recall = compute_recall(results)
    assert recall["hits"] == 2
    assert recall["evaluable"] == 3
    assert recall["null_ref"] == 1
    assert abs(recall["recall"] - 2 / 3) < 1e-9


def test_compute_recall_all_null():
    results = [{"has_ref": False, "retrieval_hit": False}] * 5
    recall = compute_recall(results)
    assert recall["evaluable"] == 0
    assert recall["recall"] == 0.0


# ---------------------------------------------------------------------------
# aggregate_by_difficulty
# ---------------------------------------------------------------------------

def test_aggregate_by_difficulty():
    results = [
        {"difficulty": "easy", "verdict": "correct"},
        {"difficulty": "easy", "verdict": "wrong"},
        {"difficulty": "hard", "verdict": "partial"},
        {"difficulty": "hard", "verdict": "correct"},
        {"difficulty": "hard", "verdict": "error"},
    ]
    breakdown = aggregate_by_difficulty(results)
    assert breakdown["easy"]["correct"] == 1
    assert breakdown["easy"]["wrong"] == 1
    assert breakdown["easy"]["total"] == 2
    assert breakdown["hard"]["partial"] == 1
    assert breakdown["hard"]["correct"] == 1
    assert breakdown["hard"]["error"] == 1
    assert breakdown["hard"]["total"] == 3
