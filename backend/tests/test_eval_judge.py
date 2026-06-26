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
# _get_judge_config — provider resolution
# ---------------------------------------------------------------------------

def test_get_judge_config_uses_llm_vars_when_set(monkeypatch):
    from scripts.eval_judge import _get_judge_config

    monkeypatch.delenv("JUDGE_PROVIDER", raising=False)
    monkeypatch.delenv("JUDGE_BASE_URL", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_API_KEY", "local")
    monkeypatch.setenv("LLM_MODEL", "google/gemma-4-e4b")

    cfg = _get_judge_config()
    assert cfg == {
        "base_url": "http://localhost:1234/v1",
        "api_key": "local",
        "model": "google/gemma-4-e4b",
    }


def test_get_judge_config_forces_gemini_when_judge_provider_gemini(monkeypatch):
    # Even with LLM_* fully set (needed for local generation), JUDGE_PROVIDER=gemini
    # must force the Gemini judge path by returning None.
    from scripts.eval_judge import _get_judge_config

    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_API_KEY", "local")
    monkeypatch.setenv("LLM_MODEL", "google/gemma-4-e4b")
    monkeypatch.setenv("JUDGE_PROVIDER", "gemini")

    assert _get_judge_config() is None


def test_get_judge_config_judge_provider_is_case_insensitive(monkeypatch):
    from scripts.eval_judge import _get_judge_config

    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("LLM_API_KEY", "local")
    monkeypatch.setenv("LLM_MODEL", "google/gemma-4-e4b")
    monkeypatch.setenv("JUDGE_PROVIDER", "Gemini")

    assert _get_judge_config() is None


# ---------------------------------------------------------------------------
# _judge_timeout_s — judge call timeout resolution
# ---------------------------------------------------------------------------

def test_judge_timeout_s_defaults_to_30(monkeypatch):
    from scripts.eval_judge import _judge_timeout_s

    monkeypatch.delenv("JUDGE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("GEMINI_TIMEOUT_S", raising=False)
    assert _judge_timeout_s() == 30.0


def test_judge_timeout_s_honors_gemini_timeout(monkeypatch):
    # A slow local judge needs the same headroom as generation; reusing the
    # GEMINI_TIMEOUT_S knob avoids verdicts coming back as timeout errors.
    from scripts.eval_judge import _judge_timeout_s

    monkeypatch.delenv("JUDGE_TIMEOUT_S", raising=False)
    monkeypatch.setenv("GEMINI_TIMEOUT_S", "150")
    assert _judge_timeout_s() == 150.0


def test_judge_timeout_s_judge_specific_overrides_gemini(monkeypatch):
    from scripts.eval_judge import _judge_timeout_s

    monkeypatch.setenv("GEMINI_TIMEOUT_S", "150")
    monkeypatch.setenv("JUDGE_TIMEOUT_S", "90")
    assert _judge_timeout_s() == 90.0


def test_judge_timeout_s_non_numeric_falls_back_to_default(monkeypatch):
    # A non-numeric value (e.g. "60s", "2m") used to raise ValueError INSIDE
    # judge_answer's try/except, turning EVERY verdict into 'error' with the cause
    # buried in each justification. It must fall back to the 30s default instead.
    from scripts.eval_judge import _judge_timeout_s

    monkeypatch.delenv("GEMINI_TIMEOUT_S", raising=False)
    monkeypatch.setenv("JUDGE_TIMEOUT_S", "60s")
    assert _judge_timeout_s() == 30.0


def test_judge_timeout_s_zero_or_negative_falls_back_to_default(monkeypatch):
    # JUDGE_TIMEOUT_S=0 parsed to 0.0 = immediate timeout (every call dies); a
    # non-positive timeout is never what the operator meant — use the default.
    from scripts.eval_judge import _judge_timeout_s

    monkeypatch.delenv("GEMINI_TIMEOUT_S", raising=False)
    monkeypatch.setenv("JUDGE_TIMEOUT_S", "0")
    assert _judge_timeout_s() == 30.0
    monkeypatch.setenv("JUDGE_TIMEOUT_S", "-5")
    assert _judge_timeout_s() == 30.0


def test_judge_gemini_uses_configurable_timeout(monkeypatch):
    # The Gemini judge path (forced via JUDGE_PROVIDER=gemini) must honour the same
    # JUDGE_TIMEOUT_S/GEMINI_TIMEOUT_S knob as the openai_compat path — it used to
    # be hardcoded at 30s, so the forced-judge mode this harness supports ignored
    # the override.
    from scripts.eval_judge import _judge_gemini

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.delenv("GEMINI_TIMEOUT_S", raising=False)
    monkeypatch.setenv("JUDGE_TIMEOUT_S", "150")

    with (
        patch("google.genai.Client"),
        patch("app.rag.generation._call_gemini", return_value='{"verdict": "correct", "justification": "x"}') as mock_call,
    ):
        _judge_gemini("prompt")
        assert mock_call.call_args.kwargs["timeout_s"] == 150.0


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
