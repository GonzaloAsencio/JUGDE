"""Phase 0 diagnostic: split failed eval questions into retrieval vs reasoning.

Crosses the LLM-judge verdicts stored in an eval results JSON with the
deterministic retrieval probe (has_ref / retrieval_hit) that scripts/eval.py
already computes per question:

  - has_ref and not retrieval_hit  -> RETRIEVAL failure (gold never reached context)
  - has_ref and retrieval_hit      -> REASONING failure (gold was in context, still wrong)
  - not has_ref                    -> UNKNOWN (question lacks a rule_reference annotation)

Usage:
  PYTHONPATH=. python -m scripts.diagnose_hard [--file data/eval_results_X.json]

With no --file, uses the most recent data/eval_results_*.json.
Read-only: never calls the LLM, the DB, or the embedder.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FAILED_VERDICTS = {"wrong", "partial"}


def _latest_results_file() -> Path:
    candidates = sorted(DATA_DIR.glob("eval_results_*.json"))
    if not candidates:
        raise SystemExit(f"No eval_results_*.json found in {DATA_DIR}")
    return candidates[-1]


def classify(q: dict) -> str:
    """Bucket a single failed question. Pure — unit-testable."""
    if not q.get("has_ref"):
        return "unknown"
    return "reasoning" if q.get("retrieval_hit") else "retrieval"


def diagnose(questions: list[dict]) -> dict:
    """Aggregate failure buckets per difficulty. Pure — unit-testable."""
    out: dict = {}
    for q in questions:
        diff = q.get("difficulty", "?")
        d = out.setdefault(
            diff,
            {"total": 0, "failed": 0, "error": 0,
             "retrieval": [], "reasoning": [], "unknown": []},
        )
        d["total"] += 1
        verdict = q.get("verdict")
        if verdict == "error":
            d["error"] += 1
            continue
        if verdict in FAILED_VERDICTS:
            d["failed"] += 1
            d[classify(q)].append(q["id"])
    return out


def tag_breakdown(questions: list[dict], eval_set: dict | None) -> Counter:
    """Count tags across failed questions (needs eval_set.json for tags)."""
    if eval_set is None:
        return Counter()
    tags_by_id = {q["id"]: q.get("tags", []) for q in eval_set["questions"]}
    counter: Counter = Counter()
    for q in questions:
        if q.get("verdict") in FAILED_VERDICTS:
            counter.update(tags_by_id.get(q["id"], []))
    return counter


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=None,
                        help="eval results JSON (default: latest in data/)")
    args = parser.parse_args()

    path = args.file or _latest_results_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"]

    eval_set_path = DATA_DIR / "eval_set.json"
    eval_set = (json.loads(eval_set_path.read_text(encoding="utf-8"))
                if eval_set_path.exists() else None)

    print(f"Diagnosing: {path.name}  ({len(questions)} questions)\n")

    buckets = diagnose(questions)
    for diff in ("easy", "medium", "hard"):
        if diff not in buckets:
            continue
        d = buckets[diff]
        print(f"[{diff}] total={d['total']} failed={d['failed']} error={d['error']}")
        for kind in ("retrieval", "reasoning", "unknown"):
            ids = d[kind]
            print(f"    {kind:10s}: {len(ids):2d}  {', '.join(ids)}")
        print()

    hard = buckets.get("hard")
    if hard and hard["failed"]:
        known = len(hard["retrieval"]) + len(hard["reasoning"])
        print("HARD bucket split (the Phase 0 number):")
        if known:
            r = len(hard["retrieval"]) / known
            print(f"  Of {known} classifiable failures: "
                  f"{r:.0%} retrieval / {1 - r:.0%} reasoning")
        if hard["unknown"]:
            print(f"  UNCLASSIFIABLE: {len(hard['unknown'])} failures lack "
                  f"rule_reference -> annotate first: {', '.join(hard['unknown'])}")
        print()

    top_tags = tag_breakdown(questions, eval_set).most_common(12)
    if top_tags:
        print("Failed-question tag breakdown (all difficulties):")
        for tag, n in top_tags:
            print(f"    {n:2d}  {tag}")


if __name__ == "__main__":
    main()
