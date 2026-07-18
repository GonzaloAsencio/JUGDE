"""Flip-gate probe for hyde_model (plan 2.2) — does a cheap HyDE writer degrade
retrieval?

The HyDE passage is 2-3 throwaway sentences that only get EMBEDDED, never
shown, so it should not need the answering model. The flag routes the passage
to a smaller model on the SAME provider endpoint (a design constraint:
OpenAICompatProvider reuses its base_url/key for hyde). Candidate measured
here: whatever HYDE_CANDIDATE says — gemma-4-31b at the time of writing, the
only clearly-smaller model Cerebras exposes.

What can actually break: a worse passage embeds differently, the fused context
shifts, and a gold rule that used to reach the model no longer does. So the
gate reads GOLD-REF COVERAGE of the real production context, built twice per
question — once with the main model's passage, once with the candidate's —
via the same _retrieve production runs and the same coverage helpers every
probe uses (per_ref_ranks / fully_covered, imported — not copied — from
retrieval_probe).

The pre-committed rule lives in docs/improvement-plan.md §2.2:
  * Universe: the non-routed evaluable questions. With the 2.1 flip, routed
    queries never call HyDE at all — the flag can only affect these.
  * KILL: the candidate arm LOSES coverage of a gold ref the main arm covers,
    CONFIRMED by a re-run — passages are sampled, so a one-off flip is not
    evidence; the regression must persist in a second candidate passage.
  * Ties and wins -> ALIVE. Wins (candidate covers what main missed) and arm
    latencies are reported as information, never as the verdict.
  * confidence deltas are reported with the same human-review threshold the
    2.1 gate used (imported from hyde_skip_probe — one copy).

Cost: ~2 hyde calls per question on the main provider (plus one per confirmed
re-run), ZERO Gemini, zero judge.

Usage (from backend/):
    python -m scripts.hyde_model_probe
"""
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import _detect_entities, _detect_keywords, _extract_tags, _retrieve
from app.rag.provider import OpenAICompatProvider
from app.rag.routing import should_route
from scripts.eval_judge import _parse_refs
from scripts.hyde_skip_probe import CONFIDENCE_DROP_REVIEW
from scripts.retrieval_probe import _resolve_corpus_version, per_ref_ranks

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

HYDE_CANDIDATE = "gemma-4-31b"


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_hyde_model_probe.py)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArmResult:
    """One arm's production context, reduced to what the gate reads."""
    covered: frozenset  # gold refs present in the assembled context
    confidence: float
    latency_s: float


@dataclass(frozen=True)
class QuestionResult:
    id: str
    refs: tuple
    main: ArmResult
    cheap: ArmResult
    # Refs main covers and cheap does not, on BOTH candidate passages (the
    # re-run confirmation already applied). Empty = no persistent regression.
    persistent_regressions: frozenset = field(default_factory=frozenset)

    @property
    def wins(self) -> frozenset:
        return self.cheap.covered - self.main.covered

    @property
    def confidence_drop(self) -> float:
        return self.main.confidence - self.cheap.confidence


def regressions(main_covered: frozenset, cheap_covered: frozenset) -> frozenset:
    """Gold refs the main arm covers that the candidate arm lost."""
    return main_covered - cheap_covered


def gate_verdict(results: list[QuestionResult]) -> str:
    """The pre-committed rule (plan §2.2): any persistent regression kills.

    An empty result list is a broken run, not a passing one.
    """
    if not results:
        return "DEAD"
    return "DEAD" if any(r.persistent_regressions for r in results) else "ALIVE"


def confidence_review(results: list[QuestionResult]) -> list[str]:
    """IDs whose confidence drops past the shared human-review threshold."""
    return [r.id for r in results if r.confidence_drop > CONFIDENCE_DROP_REVIEW]


# ---------------------------------------------------------------------------
# DB/LLM-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_universe(pool, corpus_version) -> list[dict]:
    """Non-routed evaluable questions — the only ones the flag can touch."""
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    qs = data["questions"] if isinstance(data, dict) and "questions" in data else data
    out = []
    for q in qs:
        if q.get("rule_reference") is None:
            continue
        clean, _ = _extract_tags(q["question"])
        base = clean or q["question"]
        entities = _detect_entities(base, pool, corpus_version, "hyde-model-probe")
        routed = should_route(
            routing_enabled=True,
            card_count=entities.card_count([]),
            keyword_count=len(_detect_keywords(base)),
        )
        if not routed:
            out.append(q)
    return out


def _make_provider(settings, hyde_model: str | None) -> OpenAICompatProvider:
    # Mirrors provider.create_provider's openai_compat branch; built directly so
    # the two arms differ ONLY in hyde_model.
    return OpenAICompatProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.gemini_temperature,
        timeout_s=settings.gemini_timeout_s,
        max_output_tokens=settings.max_output_tokens,
        hyde_model=hyde_model,
    )


def _run_arm(question, refs, provider, embedder, pool, settings, corpus_version) -> ArmResult:
    t0 = time.time()
    chunks, _, confidence, _, _ = _retrieve(
        question, embedder, pool, provider, settings, None, corpus_version,
        "hyde-model-probe", skip_hyde=False,
    )
    covered = frozenset(
        ref for ref, rank in per_ref_ranks(list(refs), chunks).items() if rank is not None
    )
    return ArmResult(covered=covered, confidence=confidence, latency_s=time.time() - t0)


def main() -> None:
    settings = Settings()
    if settings.llm_provider != "openai_compat":
        sys.exit("This gate mirrors prod: set LLM_PROVIDER=openai_compat (.env aligned to prod).")

    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")
    print(f"  main hyde writer      : {settings.llm_model}")
    print(f"  candidate hyde writer : {HYDE_CANDIDATE}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)

    main_arm_provider = _make_provider(settings, None)
    cheap_arm_provider = _make_provider(settings, HYDE_CANDIDATE)

    results: list[QuestionResult] = []
    try:
        universe = _load_universe(pool, corpus_version)
        print(f"  universe: {len(universe)} non-routed evaluable questions\n")
        for q in universe:
            qid = q.get("id", "?")
            refs = tuple(_parse_refs(q["rule_reference"]))
            main_res = _run_arm(q["question"], refs, main_arm_provider,
                                embedder, pool, settings, corpus_version)
            cheap_res = _run_arm(q["question"], refs, cheap_arm_provider,
                                 embedder, pool, settings, corpus_version)
            lost = regressions(main_res.covered, cheap_res.covered)
            persistent = frozenset()
            if lost:
                print(f"    {qid}: candidate lost {sorted(lost)} — re-running for confirmation...")
                cheap_retry = _run_arm(q["question"], refs, cheap_arm_provider,
                                       embedder, pool, settings, corpus_version)
                persistent = lost & regressions(main_res.covered, cheap_retry.covered)
            results.append(QuestionResult(
                id=qid, refs=refs, main=main_res, cheap=cheap_res,
                persistent_regressions=persistent,
            ))
            flag = "REGRESSION!" if persistent else ("transient" if lost else "ok")
            print(f"    {qid:10s} main={len(main_res.covered)}/{len(refs)} "
                  f"cheap={len(cheap_res.covered)}/{len(refs)} "
                  f"lat {main_res.latency_s:5.1f}s vs {cheap_res.latency_s:5.1f}s  {flag}")
    finally:
        close_pool(pool)

    verdict = gate_verdict(results)
    review = confidence_review(results)
    wins = [(r.id, sorted(r.wins)) for r in results if r.wins]

    print("\n" + "=" * 64)
    print("HYDE MODEL FLIP GATE (hyde_model — plan §2.2)")
    print("=" * 64)
    print(f"  Universe: {len(results)} non-routed evaluable questions")
    dead = [r for r in results if r.persistent_regressions]
    if dead:
        print("  PERSISTENT COVERAGE REGRESSIONS (each one kills the flag):")
        for r in dead:
            print(f"    {r.id}: {sorted(r.persistent_regressions)}")
    else:
        print("  Coverage: zero persistent regressions [OK]")
    if wins:
        print(f"  Wins (informational): {wins}")
    lat_main = sum(r.main.latency_s for r in results)
    lat_cheap = sum(r.cheap.latency_s for r in results)
    print(f"  Total arm latency: main {lat_main:.0f}s vs candidate {lat_cheap:.0f}s")
    if review:
        print(f"  Confidence drops > {CONFIDENCE_DROP_REVIEW} — HUMAN CALL: {', '.join(review)}")
    else:
        print(f"  No confidence drop exceeds the {CONFIDENCE_DROP_REVIEW} review threshold [OK]")
    print(f"\n  VERDICT: {verdict}")
    print("=" * 64)


if __name__ == "__main__":
    main()
