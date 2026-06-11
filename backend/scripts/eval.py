"""Eval harness for the Judge RAG pipeline (LLM-as-judge + retrieval recall).

Usage (from backend/):
    python -m scripts.eval

Requires: DB with corpus ingestado, GEMINI_API_KEY (or JUDGE_* + LLM_* env vars).
Redis cache is intentionally NOT initialised — every question hits generation fresh.
"""
import asyncio
import json
import os
import sys
import time
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
    aggregate_by_difficulty,
    aggregate_by_source,
    compute_recall,
    judge_answer,
    match_rule_reference,
)

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"
_RESULTS_DIR = Path(__file__).parent.parent / "data"

_VERDICT_ICON = {"correct": "OK", "partial": "~~", "wrong": "NO", "error": "ER"}


def _load_eval_set() -> list[dict]:
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


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

        results.append({
            "id": q.get("id", f"q{i}"),
            "question": q["question"],
            "difficulty": q.get("difficulty", "unknown"),
            "source": q.get("source", "unknown"),
            "rule_reference": q.get("rule_reference"),
            "has_ref": has_ref,
            "verdict": verdict,
            "justification": judgment["justification"],
            "retrieval_hit": retrieval_hit,
            "confidence": pipeline_result["confidence"],
            "latency_ms": pipeline_result["latency_ms"],
            "answer_preview": pipeline_result["answer"][:300],
        })

    return results


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


def main() -> None:
    print("Loading eval set...")
    questions = _load_eval_set()
    print(f"  {len(questions)} questions loaded.")

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

    judge_mode = "openai_compat (JUDGE_*)" if os.getenv("JUDGE_BASE_URL") else (
        "gemini (GEMINI_API_KEY)" if os.getenv("GEMINI_API_KEY") else
        f"openai_compat (LLM_* fallback — shares quota with pipeline!)"
    )
    print(f"  Judge: {judge_mode}")

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
