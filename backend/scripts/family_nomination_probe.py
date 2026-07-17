"""Family-nomination probe — gates plan 3.11.1 lever (d) with ZERO product code.

The question it answers: should a rule family be completed when the family is
already in the context via ANY route, instead of only when a TAGGED KEYWORD
nominated it?

Why it exists (3.11.0 triage): eval-020 is a granularity miss, not a semantic
gap. Its context already holds '383. Triggered Abilities' (vector ranks 4 and
6) — only the sibling chunk carrying 383.3.d is absent. Production's completion
never fires for it because the gate nominates families from `auto_chunks`
(tagged_lookup over detected KEYWORDS), so a family that arrived through the
VECTOR arm doesn't qualify. The gate asks for the wrong door.

CONTROL   = production today: completion nominated by keyword-tagged sections.
TREATMENT = completion nominated by the rule sections already in the context.

Both run the REAL _retrieve, the REAL family_lookup and the REAL
_complete_keyword_families — no local copy of the assembly, because a probe that
re-implements the pipeline drifts from it (see docs/improvement-plan.md Fase 6).
Fidelity detail that matters: TREATMENT is built from a context retrieved with
completion DISABLED, then completed ONCE at the same cap. Stacking it on top of
CONTROL's tail instead would let the tail reach 2x the cap and flatter the
result.

PRE-COMMITTED GATE (fixed before the first run, per plan 3.11.1):
  WIN  iff eval-020 gains 383.3.d AND no other question loses a gold ref.
  Completion is append-only, so a loss would mean the append-only contract is
  broken — that is itself the finding.
  Report also carries the cost: context growth per question. A win on coverage
  that triples every context is a decision for a human, not an automatic ship.

Usage (from backend/):
    python -m scripts.family_nomination_probe

Requires: DATABASE_URL + corpus ingestado. Does NOT require any LLM API key.
"""
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import (
    _KNOWN_KEYWORDS,
    _RULE_SECTION,
    _complete_keyword_families,
    _detect_entities,
    _detect_keywords,
    _extract_tags,
    _retrieve,
)
from app.rag.retrieval import family_lookup
from app.rag.routing import build_stuffed_chunks
from scripts.eval_judge import _parse_refs
from scripts.retrieval_probe import (
    _NoHydeProvider,
    _load_evaluable,
    _resolve_corpus_version,
    fully_covered,
    per_ref_ranks,
    routing_decision,
)


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_family_nomination_probe.py)
# ---------------------------------------------------------------------------

def context_rule_sections(chunks) -> list[str]:
    """The rule-family section labels present in a context, sorted.

    This is the TREATMENT's nomination rule, and the whole proposed change:
    production nominates from keyword-tagged chunks (pipeline.py:464), which
    misses a family that reached the context through the vector arm.
    """
    return sorted({
        c.section for c in chunks
        if c.section and _RULE_SECTION.match(c.section)
    })


def lost_refs(control_per_ref: dict, treatment_per_ref: dict) -> list[str]:
    """Gold refs present in CONTROL but absent in TREATMENT.

    Completion only ever APPENDS beyond top_k, so this must always be empty.
    A non-empty result means the append-only contract is broken — the gate
    fails and that breakage is the finding.
    """
    return [
        ref for ref, rank in control_per_ref.items()
        if rank is not None and treatment_per_ref.get(ref) is None
    ]


def gained_refs(control_per_ref: dict, treatment_per_ref: dict) -> list[str]:
    """Gold refs absent in CONTROL that TREATMENT brings into the context."""
    return [
        ref for ref, rank in control_per_ref.items()
        if rank is None and treatment_per_ref.get(ref) is not None
    ]


# ---------------------------------------------------------------------------
# DB-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def run_probe(questions, embedder, pool, corpus_version, settings) -> list[dict]:
    provider = _NoHydeProvider()
    routing_enabled = settings.hard_query_routing
    relaxed = settings.hard_routing_relaxed
    cap = settings.keyword_family_extra
    # TREATMENT's base must carry NO completion, so the single cap below models
    # production's future behaviour instead of stacking two tails.
    settings_no_completion = settings.model_copy(update={"keyword_family_extra": 0})

    results = []
    for q in questions:
        refs = _parse_refs(q["rule_reference"])
        question = q["question"]
        clean_question, _ = _extract_tags(question)
        base_question = clean_question or question
        embedding = embedder.encode(base_question)
        entities = _detect_entities(base_question, pool, corpus_version, "probe")

        routed = routing_decision(
            card_count=entities.card_count([]),
            keyword_count=len(_detect_keywords(base_question)),
            routing_enabled=routing_enabled,
            relaxed=relaxed,
        )
        if routed:
            # A routed question never sees this code path — its context is the
            # whole rulebook. Recorded, not treated, so the blast radius is not
            # inflated by questions the change cannot touch.
            stuffed = build_stuffed_chunks(base_question, known_keywords=_KNOWN_KEYWORDS)
            if stuffed is not None:
                per_ref = per_ref_ranks(refs, stuffed)
                results.append({
                    "id": q.get("id", "?"), "routed": True,
                    "control_per_ref": per_ref, "treatment_per_ref": per_ref,
                    "control_size": len(stuffed), "treatment_size": len(stuffed),
                })
                continue

        control, _, _, _, _ = _retrieve(
            question, embedder, pool, provider, settings, None, corpus_version,
            "probe", question_embedding=embedding, entities=entities, skip_hyde=True,
        )
        base, _, _, _, _ = _retrieve(
            question, embedder, pool, provider, settings_no_completion, None,
            corpus_version, "probe", question_embedding=embedding, entities=entities,
            skip_hyde=True,
        )
        sections = context_rule_sections(base)
        family = family_lookup(pool, sections, corpus_version) if sections else []
        treatment = _complete_keyword_families(base, family, cap)

        results.append({
            "id": q.get("id", "?"),
            "routed": False,
            "control_per_ref": per_ref_ranks(refs, control),
            "treatment_per_ref": per_ref_ranks(refs, treatment),
            "control_size": len(control),
            "treatment_size": len(treatment),
            "sections": sections,
        })
    return results


def _print_report(results: list[dict], cap: int) -> None:
    treatable = [r for r in results if not r["routed"]]
    print("\n" + "=" * 72)
    print("FAMILY-NOMINATION PROBE — 3.11.1 lever (d)")
    print("=" * 72)
    print(f"  keyword_family_extra (cap) : {cap}")
    print(f"  questions                  : {len(results)}  "
          f"({len(treatable)} treatable / {len(results) - len(treatable)} routed, untouched)")

    gained = [(r["id"], g) for r in treatable if (g := gained_refs(r["control_per_ref"], r["treatment_per_ref"]))]
    lost = [(r["id"], l) for r in treatable if (l := lost_refs(r["control_per_ref"], r["treatment_per_ref"]))]

    print("\n  --- GATE ---")
    print(f"  GAINED refs : {len(gained)} questions")
    for qid, refs in gained:
        print(f"    + {qid:10s} {', '.join(refs)}")
    print(f"  LOST refs   : {len(lost)} questions   (append-only -> must be 0)")
    for qid, refs in lost:
        print(f"    - {qid:10s} {', '.join(refs)}")

    ctrl_full = sum(1 for r in results if fully_covered(r["control_per_ref"]))
    treat_full = sum(1 for r in results if fully_covered(r["treatment_per_ref"]))
    print(f"\n  fully-covered questions: CONTROL {ctrl_full}/{len(results)} "
          f"-> TREATMENT {treat_full}/{len(results)}")

    # The cost side of the gate: a coverage win that bloats every context is a
    # human decision, not an automatic ship.
    print("\n  --- COST: context growth on treatable questions ---")
    grew = [r for r in treatable if r["treatment_size"] > r["control_size"]]
    total_c = sum(r["control_size"] for r in treatable)
    total_t = sum(r["treatment_size"] for r in treatable)
    print(f"  questions whose context grew : {len(grew)}/{len(treatable)}")
    print(f"  total chunks                 : {total_c} -> {total_t} "
          f"({(total_t / total_c - 1) * 100:+.0f}%)")
    if grew:
        worst = max(grew, key=lambda r: r["treatment_size"] - r["control_size"])
        print(f"  worst single growth          : {worst['id']} "
              f"{worst['control_size']} -> {worst['treatment_size']}")

    print("\n  Per-question (treatable only):")
    for r in treatable:
        mark = "GAIN" if gained_refs(r["control_per_ref"], r["treatment_per_ref"]) else (
            "LOSS" if lost_refs(r["control_per_ref"], r["treatment_per_ref"]) else "  = ")
        print(f"    {r['id']:10s} [{mark}] ctx {r['control_size']:>2}->{r['treatment_size']:<2} "
              f"sections={len(r.get('sections', []))}")
    print("=" * 72)


def main() -> None:
    print("Loading evaluable eval questions...")
    questions = _load_evaluable()
    print(f"  {len(questions)} questions with rule_reference.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")
    if settings.keyword_family_extra <= 0:
        print("WARNING: keyword_family_extra <= 0 — completion is off, "
              "TREATMENT cannot append anything.", file=sys.stderr)

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.\n")

    try:
        results = run_probe(questions, embedder, pool, corpus_version, settings)
    finally:
        close_pool(pool)

    _print_report(results, settings.keyword_family_extra)


if __name__ == "__main__":
    main()
