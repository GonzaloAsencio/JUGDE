"""Eval harness for the Judge RAG pipeline (LLM-as-judge + retrieval recall).

Usage (from backend/):
    python -m scripts.eval

Requires: DB with corpus ingestado, GEMINI_API_KEY (or JUDGE_* + LLM_* env vars).
Redis cache is intentionally NOT initialised — every question hits generation fresh.
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import answer_question
from app.rag.provider import create_provider
from scripts.eval_judge import (
    _get_judge_config,
    aggregate_by_difficulty,
    aggregate_by_source,
    compute_recall,
    judge_answer,
    match_rule_reference,
)

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"
_RESULTS_DIR = Path(__file__).parent.parent / "data"

_VERDICT_ICON = {"correct": "OK", "partial": "~~", "wrong": "NO", "error": "ER"}


def _load_questions(path: Path) -> list[dict]:
    """Load a question list from JSON, unwrapping a {"questions": [...]} envelope.

    Shared by the eval set and saved results-file loaders so the unwrap rule lives
    in ONE place — a schema change can't leave the two paths reading different shapes.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


def _load_eval_set() -> list[dict]:
    return _load_questions(_EVAL_SET)


def stratified_subset(
    questions: list[dict], limit: int | None, *, key: str = "difficulty", seed: int = 42
) -> list[dict]:
    """Deterministic stratified sample of *limit* questions.

    Preserves the proportion of each *key* stratum via largest-remainder
    allocation, so a small run stays representative across difficulty (or
    whatever *key* is) instead of biasing toward whatever comes first. Within a
    stratum the pick is a seeded sample, so runs are reproducible. The result
    keeps the original question order.

    Returns the full list unchanged when *limit* is None or >= the set size.
    Why this exists: the LLM free tier can't absorb all 40 questions per run
    without exhausting quota mid-eval and contaminating the results.
    """
    if limit is None or limit >= len(questions):
        return list(questions)
    if limit <= 0:
        return []

    groups: "OrderedDict[object, list[dict]]" = OrderedDict()
    for q in questions:
        groups.setdefault(q.get(key), []).append(q)

    total = len(questions)
    raw = {k: limit * len(v) / total for k, v in groups.items()}
    alloc = {k: int(v) for k, v in raw.items()}

    # Distribute the rounding remainder to the largest fractional parts; tie-break
    # by str(key) so the allocation is fully deterministic.
    remainder = limit - sum(alloc.values())
    for k in sorted(groups, key=lambda k: (-(raw[k] - alloc[k]), str(k)))[:remainder]:
        alloc[k] += 1

    chosen_ids: set = set()
    deficit = 0
    for k, members in groups.items():
        n = min(alloc[k], len(members))
        deficit += alloc[k] - n
        ordered = sorted(members, key=lambda q: str(q.get("id", "")))
        rnd = random.Random(f"{seed}:{k}")
        picked = ordered if n >= len(ordered) else rnd.sample(ordered, n)
        chosen_ids.update(q.get("id") for q in picked)

    # If capping a stratum left us short, top up from any leftover, deterministically.
    if deficit:
        leftovers = sorted(
            (q for q in questions if q.get("id") not in chosen_ids),
            key=lambda q: str(q.get("id", "")),
        )
        chosen_ids.update(q.get("id") for q in leftovers[:deficit])

    return [q for q in questions if q.get("id") in chosen_ids]


def select_by_ids(questions: list[dict], ids) -> list[dict]:
    """Filter to the questions whose id is in *ids*, preserving the original
    order. Unknown ids are ignored. Used to run explicit disjoint batches so a
    full clean eval can be assembled across several runs without exceeding the
    LLM daily token budget in any single run."""
    wanted = set(ids)
    return [q for q in questions if q.get("id") in wanted]


def _resolve_corpus_version(pool, settings: Settings) -> str:
    if settings.corpus_version and settings.corpus_version != "latest":
        return settings.corpus_version
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(corpus_version) FROM corpus_chunks")
            row = cur.fetchone()
    if row is None or row[0] is None:
        print("WARNING: corpus_chunks is empty — retrieval will return nothing.", file=sys.stderr)
        return "unknown"
    return row[0]


async def _pipeline_run(question: str, embedder, pool, provider, settings):
    t0 = time.time()
    try:
        response = await answer_question(question, embedder, pool, provider, settings)
        return {
            "ok": True,
            "answer": response.answer,
            "citations": response.citations,
            "confidence": response.confidence,
            "latency_ms": response.latency_ms,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "answer": "",
            "citations": [],
            "confidence": 0.0,
            "latency_ms": round((time.time() - t0) * 1000),
        }


def _build_question_result(
    q: dict, idx: int, pipeline_result: dict,
    *, has_ref: bool, retrieval_hit: bool, judgment: dict,
) -> dict:
    """Shape one question's eval record. Pure (no I/O) so it is unit-testable.

    Persists the FULL answer and canonical_answer — not just a preview — so a
    later run can re-judge saved answers with a different judge WITHOUT
    regenerating. Regeneration doubles the LLM calls per question and is what
    exhausts the free-tier quota mid-experiment.
    """
    return {
        "id": q.get("id", f"q{idx}"),
        "question": q["question"],
        "difficulty": q.get("difficulty", "unknown"),
        "source": q.get("source", "unknown"),
        "rule_reference": q.get("rule_reference"),
        "has_ref": has_ref,
        "verdict": judgment["verdict"],
        "justification": judgment["justification"],
        "retrieval_hit": retrieval_hit,
        "confidence": pipeline_result["confidence"],
        "latency_ms": pipeline_result["latency_ms"],
        "canonical_answer": q.get("canonical_answer", ""),
        "answer": pipeline_result["answer"],
        "answer_preview": pipeline_result["answer"][:300],
    }


async def run_eval(questions: list[dict], embedder, pool, provider, settings) -> list[dict]:
    results = []
    total = len(questions)

    for i, q in enumerate(questions, 1):
        label = q["question"][:55] + ("..." if len(q["question"]) > 55 else "")
        print(f"[{i:2}/{total}] {label}", end=" ", flush=True)

        pipeline_result = await _pipeline_run(q["question"], embedder, pool, provider, settings)

        if not pipeline_result["ok"]:
            print(f"  [pipeline error] {pipeline_result.get('error', '')[:120]}")

        has_ref = q.get("rule_reference") is not None
        retrieval_hit = False
        if has_ref and pipeline_result["ok"]:
            retrieval_hit = match_rule_reference(
                q["rule_reference"], pipeline_result["citations"]
            )

        if pipeline_result["ok"]:
            judgment = judge_answer(
                q["question"], q["canonical_answer"], pipeline_result["answer"]
            )
        else:
            judgment = {
                "verdict": "error",
                "justification": f"Pipeline error: {pipeline_result.get('error', 'unknown')}",
            }

        verdict = judgment["verdict"]
        icon = _VERDICT_ICON.get(verdict, "?")
        hit_str = ("H" if retrieval_hit else "M") if has_ref else "-"
        print(f"{icon} ret={hit_str} conf={pipeline_result['confidence']:.2f} {pipeline_result['latency_ms']}ms")

        if i < total:
            await asyncio.sleep(2)

        results.append(_build_question_result(
            q, i, pipeline_result,
            has_ref=has_ref, retrieval_hit=retrieval_hit, judgment=judgment,
        ))

    return results


def rejudge_results(saved: list[dict], *, judge=judge_answer) -> list[dict]:
    """Re-score saved answers with the current judge, WITHOUT regenerating.

    Reads back each persisted full answer + canonical_answer and re-runs only the
    judge — no DB, embedder, or generation. Retrieval-derived fields (has_ref,
    retrieval_hit) are deterministic and carried over unchanged. Records that
    predate full-answer persistence (no 'answer'/'canonical_answer') are marked
    verdict='error' since they cannot be faithfully re-judged.

    Why this exists: swapping the judge (e.g. weak local vs strong cloud) used to
    require a full re-run, doubling LLM calls and exhausting the free-tier quota.
    """
    out = []
    total = len(saved)
    for i, q in enumerate(saved, 1):
        question = q.get("question", "")
        label = question[:55] + ("..." if len(question) > 55 else "")
        print(f"[{i:2}/{total}] {label}", end=" ", flush=True)

        answer = q.get("answer")
        canonical = q.get("canonical_answer")
        if not answer or not canonical:
            judgment = {
                "verdict": "error",
                "justification": "Cannot re-judge: saved result lacks full "
                                 "answer/canonical_answer (re-run generation first)",
            }
        else:
            judgment = judge(question, canonical, answer)

        prev = q.get("verdict", "?")
        rec = {**q, "verdict": judgment["verdict"], "justification": judgment["justification"]}
        print(f"{_VERDICT_ICON.get(rec['verdict'], '?')}  (was {prev})")
        out.append(rec)

    return out


def _judge_mode_label() -> str:
    """Human label for which judge will run.

    Derived from the SAME resolution _get_judge_config performs, so the banner can
    never contradict the judge actually used. A bare JUDGE_BASE_URL (without
    JUDGE_API_KEY/JUDGE_MODEL) does NOT yield an openai_compat config — the judge
    falls through to Gemini — and the label must say so.
    """
    if os.getenv("JUDGE_PROVIDER", "").lower() == "gemini":
        return "gemini (forced via JUDGE_PROVIDER)"
    if _get_judge_config() is not None:
        # Config resolved. Distinguish the dedicated JUDGE_* endpoint from the
        # LLM_* fallback, which shares rate-limit quota with the pipeline.
        if os.getenv("JUDGE_BASE_URL") and os.getenv("JUDGE_API_KEY") and os.getenv("JUDGE_MODEL"):
            return "openai_compat (JUDGE_*)"
        return "openai_compat (LLM_* fallback — shares quota with pipeline!)"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini (GEMINI_API_KEY)"
    return "NONE — judge will error (set JUDGE_*/LLM_*/GEMINI_API_KEY)"


def _print_report(results: list[dict]) -> None:
    total = len(results)
    verdicts = {v: sum(1 for r in results if r["verdict"] == v) for v in ("correct", "partial", "wrong", "error")}
    recall = compute_recall(results)
    avg_conf = sum(r["confidence"] for r in results) / total if total else 0.0
    avg_latency = sum(r["latency_ms"] for r in results) / total if total else 0.0

    print("\n" + "=" * 60)
    print("EVAL RESULTS")
    print("=" * 60)
    print(f"  Total questions : {total}")
    if not total:
        print("  (no results to report)")
        print("=" * 60)
        return
    print(f"  Accuracy (judge): correct={verdicts['correct']} partial={verdicts['partial']} wrong={verdicts['wrong']} error={verdicts['error']}")
    print(f"  Correct rate    : {verdicts['correct'] / total:.0%}  (correct+partial: {(verdicts['correct'] + verdicts['partial']) / total:.0%})")
    print(f"  Retrieval recall: {recall['hits']}/{recall['evaluable']} evaluable questions = {recall['recall']:.0%}")
    print(f"    ({recall['null_ref']} questions excluded — no rule_reference)")
    print(f"  Avg confidence  : {avg_conf:.3f}")
    print(f"  Avg latency     : {avg_latency:.0f}ms")

    print("\n  By difficulty:")
    for diff, counts in sorted(aggregate_by_difficulty(results).items()):
        acc = counts["correct"] / counts["total"] if counts["total"] else 0.0
        print(f"    {diff:8s}: {counts['correct']}ok {counts['partial']}~~ {counts['wrong']}no {counts['error']}er / {counts['total']} ({acc:.0%})")

    print("\n  By source:")
    for src, counts in sorted(aggregate_by_source(results).items()):
        acc = counts["correct"] / counts["total"] if counts["total"] else 0.0
        print(f"    {src:12s}: {counts['correct']}ok {counts['partial']}~~ {counts['wrong']}no {counts['error']}er / {counts['total']} ({acc:.0%})")

    print("\n  NOTE: judge verdicts are non-deterministic (LLM). Retrieval recall is deterministic.")
    print("=" * 60)


def _save_results(results: list[dict]) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = _RESULTS_DIR / f"eval_results_{ts}.json"
    payload = {
        "timestamp": ts,
        "total": len(results),
        "recall": compute_recall(results),
        "by_difficulty": aggregate_by_difficulty(results),
        "by_source": aggregate_by_source(results),
        "questions": results,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Eval harness for the Judge RAG pipeline.")
    p.add_argument(
        "--limit", type=int, default=None,
        help="Run a stratified subset of N questions (preserves difficulty mix). "
             "Default: all questions. Use when the LLM free tier can't absorb the full set.",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="Seed for the stratified subset pick (reproducible runs). Default: 42.",
    )
    p.add_argument(
        "--ids", type=str, default=None,
        help="Comma-separated question ids to run (explicit disjoint batch). "
             "Overrides --limit. Lets you assemble a clean full eval across runs.",
    )
    p.add_argument(
        "--rejudge", type=str, default=None, metavar="RESULTS_JSON",
        help="Re-score the saved answers in a previous eval_results_*.json with "
             "the CURRENT judge (set via JUDGE_*/JUDGE_PROVIDER), WITHOUT "
             "regenerating. No DB/embedder/generation. Needs a results file that "
             "has full answers (produced by this harness version).",
    )
    return p.parse_args(argv)


def _load_results_file(path: str) -> list[dict]:
    return _load_questions(Path(path))


def main() -> None:
    args = _parse_args()

    if args.rejudge:
        print(f"Re-judging saved results: {args.rejudge}")
        saved = _load_results_file(args.rejudge)
        print(f"  {len(saved)} saved questions loaded.")
        print(f"  Judge: {_judge_mode_label()}")
        print("\nRe-judging (no generation — scoring the saved answers):\n")
        results = rejudge_results(saved)
        _print_report(results)
        out_path = _save_results(results)
        print(f"\nResults saved: {out_path}")
        return

    print("Loading eval set...")
    questions = _load_eval_set()
    print(f"  {len(questions)} questions loaded.")

    from collections import Counter
    if args.ids:
        ids = [s.strip() for s in args.ids.split(",") if s.strip()]
        questions = select_by_ids(questions, ids)
        if not questions:
            print(f"  No questions matched --ids {args.ids!r} — nothing to run.")
            return
        mix = dict(Counter(q.get("difficulty", "unknown") for q in questions))
        print(f"  Explicit ids: {len(questions)} questions, difficulty mix {mix}")
        print(f"  ids: {', '.join(q.get('id', '?') for q in questions)}")
    elif args.limit is not None and args.limit < len(questions):
        questions = stratified_subset(questions, args.limit, seed=args.seed)
        mix = dict(Counter(q.get("difficulty", "unknown") for q in questions))
        print(f"  Stratified subset: {len(questions)} questions (seed={args.seed}), difficulty mix {mix}")
        print(f"  ids: {', '.join(q.get('id', '?') for q in questions)}")

    print("Loading settings...")
    settings = Settings()

    print("Initialising DB pool...")
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)

    corpus_version = _resolve_corpus_version(pool, settings)
    settings.corpus_version = corpus_version
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.")

    print("Initialising LLM provider...")
    if settings.llm_provider == "gemini":
        from google import genai
        llm_client = genai.Client(api_key=settings.gemini_api_key)
    else:
        llm_client = None
    provider = create_provider(settings, llm_client)
    print(f"  Provider: {settings.llm_provider}")

    print(f"  Judge: {_judge_mode_label()}")

    print("\nRunning eval (no Redis cache — fresh generation per question):\n")

    try:
        results = asyncio.run(run_eval(questions, embedder, pool, provider, settings))
    finally:
        close_pool(pool)

    _print_report(results)
    out_path = _save_results(results)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
