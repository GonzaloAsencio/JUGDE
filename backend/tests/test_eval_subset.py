"""Unit tests for the stratified subset sampler used by the eval harness.

The sampler lets us run a smaller, representative slice of the eval set when the
LLM free-tier budget can't absorb the full 40 questions in one run. It must be
deterministic (reproducible runs) and preserve the proportion of each stratum.
"""
from collections import Counter

from scripts.eval import (
    _build_question_result,
    _judge_mode_label,
    _load_questions,
    _print_report,
    rejudge_results,
    select_by_ids,
    stratified_subset,
)


def _q(id_, difficulty):
    return {"id": id_, "difficulty": difficulty, "question": f"q{id_}"}


def _dataset():
    # 5 'a', 3 'b', 2 'c' = 10 questions, in interleaved order.
    rows = (
        [("a", "a")] * 5 + [("b", "b")] * 3 + [("c", "c")] * 2
    )
    return [_q(f"eval-{i:03d}", diff) for i, (_, diff) in enumerate(rows)]


def test_limit_none_returns_all():
    qs = _dataset()
    assert stratified_subset(qs, None) == qs


def test_limit_ge_total_returns_all():
    qs = _dataset()
    assert stratified_subset(qs, 99) == qs


def test_limit_zero_returns_empty():
    assert stratified_subset(_dataset(), 0) == []


def test_returns_exactly_limit():
    qs = _dataset()
    assert len(stratified_subset(qs, 5)) == 5
    assert len(stratified_subset(qs, 7)) == 7


def test_preserves_strata_proportions_largest_remainder():
    # 5a/3b/2c, limit=5 -> raw a=2.5 b=1.5 c=1.0; floors 2/1/1 (sum 4);
    # remainder 1 goes to the largest fractional part, tie broken by key -> 'a'.
    # Expect a=3, b=1, c=1.
    qs = _dataset()
    counts = Counter(q["difficulty"] for q in stratified_subset(qs, 5))
    assert counts == {"a": 3, "b": 1, "c": 1}


def test_is_deterministic():
    qs = _dataset()
    a = [q["id"] for q in stratified_subset(qs, 6, seed=42)]
    b = [q["id"] for q in stratified_subset(qs, 6, seed=42)]
    assert a == b


def test_preserves_original_order():
    qs = _dataset()
    out = stratified_subset(qs, 6)
    ids = [q["id"] for q in out]
    assert ids == sorted(ids)  # dataset ids are already in order


def test_every_stratum_represented_when_room():
    qs = _dataset()
    counts = Counter(q["difficulty"] for q in stratified_subset(qs, 6))
    assert set(counts) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# select_by_ids — explicit disjoint batches
# ---------------------------------------------------------------------------

def test_select_by_ids_filters_and_preserves_order():
    qs = _dataset()
    out = select_by_ids(qs, ["eval-005", "eval-001", "eval-008"])
    # original order preserved, not the order given
    assert [q["id"] for q in out] == ["eval-001", "eval-005", "eval-008"]


def test_select_by_ids_ignores_unknown_ids():
    qs = _dataset()
    out = select_by_ids(qs, ["eval-099", "eval-003", "nope"])
    assert [q["id"] for q in out] == ["eval-003"]


def test_select_by_ids_empty_returns_empty():
    assert select_by_ids(_dataset(), []) == []


# ---------------------------------------------------------------------------
# _build_question_result — persists full answer + canonical for cheap re-judge
# ---------------------------------------------------------------------------

def test_build_question_result_persists_full_answer_and_canonical():
    # The FULL answer and canonical_answer must be saved (not just a preview) so a
    # later run can re-judge saved answers with a different judge WITHOUT
    # regenerating — regeneration is what burns double the LLM quota.
    q = {
        "id": "eval-001", "question": "Q?", "difficulty": "hard", "source": "ruling",
        "rule_reference": "103.2", "canonical_answer": "The canonical answer.",
    }
    long_answer = "A" * 500
    pipeline_result = {"answer": long_answer, "confidence": 0.7, "latency_ms": 1234}
    judgment = {"verdict": "correct", "justification": "ok"}

    r = _build_question_result(
        q, 1, pipeline_result, has_ref=True, retrieval_hit=True, judgment=judgment,
    )

    assert r["answer"] == long_answer
    assert r["canonical_answer"] == "The canonical answer."
    # Preview stays truncated for quick scans / backward compatibility.
    assert r["answer_preview"] == long_answer[:300]
    assert len(r["answer_preview"]) == 300
    # Core fields intact.
    assert r["id"] == "eval-001"
    assert r["verdict"] == "correct"
    assert r["has_ref"] is True
    assert r["retrieval_hit"] is True
    assert r["confidence"] == 0.7


def test_build_question_result_defaults_missing_fields():
    q = {"question": "Q?"}  # no id, no canonical, no difficulty/source
    pipeline_result = {"answer": "", "confidence": 0.0, "latency_ms": 0}
    judgment = {"verdict": "error", "justification": "boom"}

    r = _build_question_result(
        q, 3, pipeline_result, has_ref=False, retrieval_hit=False, judgment=judgment,
    )

    assert r["id"] == "q3"
    assert r["canonical_answer"] == ""
    assert r["difficulty"] == "unknown"
    assert r["source"] == "unknown"
    assert r["answer"] == ""


# ---------------------------------------------------------------------------
# rejudge_results — re-score saved answers WITHOUT regenerating
# ---------------------------------------------------------------------------

def test_rejudge_results_rescores_with_injected_judge():
    saved = [{
        "id": "eval-001", "question": "Q1", "canonical_answer": "C1", "answer": "A1",
        "difficulty": "hard", "source": "ruling", "has_ref": True, "retrieval_hit": True,
        "verdict": "wrong", "justification": "old gemma verdict",
        "confidence": 0.6, "latency_ms": 100,
    }]
    fake_judge = lambda q, c, a: {"verdict": "correct", "justification": "strong judge says ok"}

    out = rejudge_results(saved, judge=fake_judge)

    # Verdict re-scored by the new judge.
    assert out[0]["verdict"] == "correct"
    assert out[0]["justification"] == "strong judge says ok"
    # Deterministic retrieval fields + the saved answer are carried over unchanged.
    assert out[0]["retrieval_hit"] is True
    assert out[0]["has_ref"] is True
    assert out[0]["answer"] == "A1"
    assert out[0]["confidence"] == 0.6


def test_rejudge_results_passes_saved_answer_and_canonical_to_judge():
    saved = [{"question": "Q", "canonical_answer": "CANON", "answer": "GENERATED"}]
    seen = {}
    def spy_judge(q, c, a):
        seen.update(question=q, canonical=c, answer=a)
        return {"verdict": "partial", "justification": "j"}

    rejudge_results(saved, judge=spy_judge)

    assert seen == {"question": "Q", "canonical": "CANON", "answer": "GENERATED"}


def test_rejudge_results_marks_error_when_answer_missing():
    # Older result files predate full-answer persistence: cannot re-judge them.
    saved = [{"id": "x", "question": "Q", "canonical_answer": "C", "verdict": "wrong"}]
    called = []
    fake_judge = lambda q, c, a: called.append(1) or {"verdict": "correct", "justification": "x"}

    out = rejudge_results(saved, judge=fake_judge)

    assert out[0]["verdict"] == "error"
    assert "re-judge" in out[0]["justification"].lower()
    assert called == []  # judge must NOT be invoked without a full answer


# ---------------------------------------------------------------------------
# _print_report — must not crash on an empty result set
# ---------------------------------------------------------------------------

def test_print_report_empty_results_no_crash(capsys):
    # Reachable in one keystroke: `--ids <typo>` selects 0 questions, or a
    # --rejudge file with no questions. total=0 used to raise ZeroDivisionError on
    # the "Correct rate" line (avg_conf/avg_latency were already guarded).
    _print_report([])
    out = capsys.readouterr().out
    assert "Total questions : 0" in out


# ---------------------------------------------------------------------------
# _judge_mode_label — must reflect the judge actually resolved by _get_judge_config
# ---------------------------------------------------------------------------

def _clear_judge_env(monkeypatch):
    for var in (
        "JUDGE_PROVIDER", "JUDGE_BASE_URL", "JUDGE_API_KEY", "JUDGE_MODEL",
        "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL", "GEMINI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_judge_mode_label_base_url_without_creds_is_not_openai_compat(monkeypatch):
    # JUDGE_BASE_URL alone does NOT satisfy _get_judge_config (needs api_key+model
    # too), so the judge actually runs via Gemini. The label used to lie and say
    # "openai_compat (JUDGE_*)". It must follow the real resolution.
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("JUDGE_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert _judge_mode_label() == "gemini (GEMINI_API_KEY)"


def test_judge_mode_label_full_judge_vars_is_openai_compat(monkeypatch):
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("JUDGE_BASE_URL", "http://x")
    monkeypatch.setenv("JUDGE_API_KEY", "k")
    monkeypatch.setenv("JUDGE_MODEL", "m")
    assert _judge_mode_label() == "openai_compat (JUDGE_*)"


def test_judge_mode_label_llm_fallback_warns_shared_quota(monkeypatch):
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "http://x")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert "shares quota" in _judge_mode_label()


def test_judge_mode_label_forced_gemini(monkeypatch):
    _clear_judge_env(monkeypatch)
    monkeypatch.setenv("LLM_BASE_URL", "http://x")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("JUDGE_PROVIDER", "gemini")
    assert "forced" in _judge_mode_label()


# ---------------------------------------------------------------------------
# _load_questions — single loader shared by eval-set and results-file paths
# ---------------------------------------------------------------------------

def test_load_questions_unwraps_dict(tmp_path):
    import json
    p = tmp_path / "wrapped.json"
    p.write_text(json.dumps({"questions": [{"id": "a"}]}), encoding="utf-8")
    assert _load_questions(p) == [{"id": "a"}]


def test_load_questions_accepts_bare_list(tmp_path):
    import json
    p = tmp_path / "bare.json"
    p.write_text(json.dumps([{"id": "b"}]), encoding="utf-8")
    assert _load_questions(p) == [{"id": "b"}]
