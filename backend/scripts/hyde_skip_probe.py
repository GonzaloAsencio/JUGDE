"""Flip-gate probe for skip_hyde_when_routed (plan 2.1's surviving replacement).

The flag cannot change any answer by construction — routed queries swap their
retrieval for the stuffed rulebook whether or not the HyDE arm was built, and
non-routed queries never skip. A full eval A/B would therefore only measure
judge noise. What CAN fail is the MECHANISM, and that is deterministically
measurable. The pre-committed rule lives in docs/improvement-plan.md §2.1:

  1. PREDICTION IDENTITY (the central claim): the pre-retrieval prediction
     (`will_route` in answer_question) must equal the post-retrieval routing
     decision on EVERY eval question. A FALSE POSITIVE strips the HyDE arm from
     a query that keeps its retrieval — real context degradation. A FALSE
     NEGATIVE proves the design's identity claim wrong. Either kills the flag.
     The one documented divergence — build_stuffed_chunks returning None — is a
     broken deploy (missing rulebook.md), not a flag defect; it is reported
     separately and loudly, like retrieval_probe does.
  2. SAVINGS: hyde calls avoided == number of routed queries. Zero savings
     kills the flag (a no-op feature is dead code with a config surface).
  3. CONFIDENCE DELTA (--confidence): a routed query's semantic_confidence is
     computed from the raw arm alone instead of the raw+HyDE fusion. This is
     cosmetic (confidence==0.0, the only behavioural threshold, needs empty
     citations — unreachable from a cosine), but it is user-visible, so the
     rule pre-commits: any drop > 0.2 on a routed query goes to a human before
     the flip. Costs ~1 hyde call per routed query on the MAIN provider
     (Cerebras under prod config) — ZERO Gemini.

Claims 1+2 spend no LLM quota at all: prediction and decision are entity
detection + keyword scan + should_route, and the actual-path retrieval runs
with the same zero-quota HyDE-off provider every deterministic probe uses.

Usage (from backend/):
    python -m scripts.hyde_skip_probe                # claims 1+2, zero LLM
    python -m scripts.hyde_skip_probe --confidence   # + claim 3 (real hyde calls)

Requires: DATABASE_URL + corpus ingestado. Same fail-closed Settings() caveat
as retrieval_probe: the Gemini key must be PRESENT even though claims 1+2 never
spend it.
"""
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import (
    _KNOWN_KEYWORDS,
    _detect_entities,
    _detect_keywords,
    _extract_tags,
    _retrieve,
)
from app.rag.provider import create_provider
from app.rag.routing import build_stuffed_chunks, should_route
from scripts.retrieval_probe import _NoHydeProvider, _resolve_corpus_version

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

# The pre-committed human-review threshold for claim 3 (plan §2.1): a routed
# query whose displayed confidence drops by more than this under raw-only
# retrieval is surfaced for a human call before the flip.
CONFIDENCE_DROP_REVIEW = 0.2


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_hyde_skip_probe.py — no DB, no network)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GateRow:
    """One question's prediction-vs-decision comparison."""
    id: str
    predicted: bool
    actual: bool
    stuffing_unavailable: bool

    @property
    def kind(self) -> str:
        """agree | false_positive | false_negative | stuffing_unavailable.

        stuffing_unavailable is carved out of false_positive on purpose: the
        gate SAID route and stuffing failed, which is the documented
        broken-deploy degrade, not a defect in the prediction — but it still
        means this run could not measure that question's routed path.
        """
        if self.stuffing_unavailable:
            return "stuffing_unavailable"
        if self.predicted == self.actual:
            return "agree"
        return "false_positive" if self.predicted else "false_negative"


def gate_verdict(rows: list[GateRow]) -> dict:
    """Apply the pre-committed rule to the measured rows.

    KILL on any false_positive/false_negative (claim 1) or zero savings
    (claim 2). stuffing_unavailable does not kill — it invalidates the RUN
    (environment), which the report must shout about instead.
    """
    mismatches = [r for r in rows if r.kind in ("false_positive", "false_negative")]
    degraded = [r for r in rows if r.kind == "stuffing_unavailable"]
    savings = sum(1 for r in rows if r.predicted)
    alive = not mismatches and savings > 0
    return {
        "total": len(rows),
        "mismatches": mismatches,
        "degraded": degraded,
        "savings": savings,
        "verdict": "ALIVE" if alive else "DEAD",
    }


def confidence_review(deltas: dict[str, tuple[float, float]]) -> list[str]:
    """IDs whose confidence drop exceeds the pre-committed review threshold.

    *deltas* maps id -> (fused_confidence, raw_only_confidence). Drop is
    fused - raw_only: positive means the user would see a LOWER number with
    the flag on.
    """
    return [
        qid for qid, (fused, raw_only) in deltas.items()
        if fused - raw_only > CONFIDENCE_DROP_REVIEW
    ]


# ---------------------------------------------------------------------------
# DB-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_questions() -> list[dict]:
    """ALL eval questions — prediction identity applies to every query, not
    just the recall-evaluable subset retrieval_probe restricts itself to."""
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


def _measure(questions, embedder, pool, corpus_version, settings) -> list[GateRow]:
    provider = _NoHydeProvider()
    rows = []
    for q in questions:
        question = q["question"]
        clean, _ = _extract_tags(question)
        base = clean or question

        # The prediction, exactly as answer_question computes it pre-retrieval
        # (card_mentions is None on the eval path, hence card_count([])).
        entities = _detect_entities(base, pool, corpus_version, "hyde-skip-probe")
        predicted = should_route(
            routing_enabled=True,
            card_count=entities.card_count([]),
            keyword_count=len(_detect_keywords(base)),
        )

        # The decision, exactly as answer_question makes it post-retrieval —
        # including running _retrieve with skip_hyde=predicted, i.e. the world
        # the flag would actually create.
        chunks, clean_q, _, _, ret_card_count = _retrieve(
            question, embedder, pool, provider, settings, None, corpus_version,
            "hyde-skip-probe", entities=entities, skip_hyde=predicted,
        )
        resolved = clean_q or question
        gate = should_route(
            routing_enabled=True,
            card_count=ret_card_count,
            keyword_count=len(_detect_keywords(resolved)),
        )
        stuffed = (
            build_stuffed_chunks(resolved, known_keywords=_KNOWN_KEYWORDS)
            if gate else None
        )
        rows.append(GateRow(
            id=q.get("id", "?"),
            predicted=predicted,
            actual=gate and stuffed is not None,
            stuffing_unavailable=gate and stuffed is None,
        ))
    return rows


def _measure_confidence(
    questions, rows, embedder, pool, corpus_version, settings,
) -> dict[str, tuple[float, float]]:
    """Claim 3: fused vs raw-only semantic_confidence on the routed queries.

    One REAL hyde call per routed query, on the main provider. Sequential on
    purpose: Cerebras throttles bursts of ~19 (backoff pushes latency to ~60s),
    and this is not a latency measurement.
    """
    real = create_provider(settings)
    print(f"  hyde arm provider: {real.model}")
    predicted_ids = {r.id for r in rows if r.predicted}
    deltas: dict[str, tuple[float, float]] = {}
    for q in questions:
        qid = q.get("id", "?")
        if qid not in predicted_ids:
            continue
        question = q["question"]
        _, _, raw_only, _, _ = _retrieve(
            question, embedder, pool, _NoHydeProvider(), settings, None,
            corpus_version, "hyde-skip-probe", skip_hyde=True,
        )
        _, _, fused, _, _ = _retrieve(
            question, embedder, pool, real, settings, None,
            corpus_version, "hyde-skip-probe", skip_hyde=False,
        )
        deltas[qid] = (fused, raw_only)
        print(f"    {qid:10s} fused={fused:.4f}  raw-only={raw_only:.4f}  "
              f"delta={fused - raw_only:+.4f}")
    return deltas


def _print_report(result: dict, deltas: dict[str, tuple[float, float]] | None) -> None:
    print("\n" + "=" * 64)
    print("HYDE SKIP FLIP GATE (skip_hyde_when_routed — plan §2.1)")
    print("=" * 64)
    print(f"  Questions measured        : {result['total']}")
    print(f"  Claim 2 — hyde calls saved: {result['savings']}/{result['total']}")

    if result["degraded"]:
        ids = ", ".join(r.id for r in result["degraded"])
        print(f"\n  *** WARNING: stuffing UNAVAILABLE for {len(result['degraded'])} "
              f"question(s): {ids}")
        print("      This run could not measure their routed path — fix the deploy")
        print("      (data/processed/rulebook.md) and re-run before trusting this gate.")

    if result["mismatches"]:
        print("\n  Claim 1 — PREDICTION MISMATCHES (each one kills the flag):")
        for r in result["mismatches"]:
            print(f"    {r.id:10s} {r.kind}: predicted={r.predicted} actual={r.actual}")
    else:
        print("  Claim 1 — prediction == decision on every question [OK]")

    if deltas is not None:
        drops = [fused - raw for fused, raw in deltas.values()]
        review = confidence_review(deltas)
        print(f"\n  Claim 3 — confidence delta on {len(deltas)} routed queries "
              f"(fused - raw-only; positive = user sees less):")
        if drops:
            print(f"    median {statistics.median(drops):+.4f}   "
                  f"max {max(drops):+.4f}   min {min(drops):+.4f}")
        if review:
            print(f"    *** DROP > {CONFIDENCE_DROP_REVIEW} — HUMAN CALL BEFORE FLIP: "
                  f"{', '.join(review)}")
        else:
            print(f"    no drop exceeds the {CONFIDENCE_DROP_REVIEW} review threshold [OK]")

    print(f"\n  VERDICT: {result['verdict']}")
    if result["verdict"] == "ALIVE" and deltas is None:
        print("  (claims 1+2 only — run with --confidence for claim 3 before the flip)")
    print("=" * 64)


def main() -> None:
    with_confidence = "--confidence" in sys.argv

    questions = _load_questions()
    print(f"Loaded {len(questions)} eval questions.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.\n")

    try:
        rows = _measure(questions, embedder, pool, corpus_version, settings)
        result = gate_verdict(rows)
        deltas = None
        if with_confidence:
            print("Measuring claim 3 (one real hyde call per routed query)...")
            deltas = _measure_confidence(
                questions, rows, embedder, pool, corpus_version, settings,
            )
    finally:
        close_pool(pool)

    _print_report(result, deltas)


if __name__ == "__main__":
    main()
