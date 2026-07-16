"""Routing-threshold probe — gates plan 3.11.1 lever (a) with ZERO product code.

The question it answers: should is_hard_query route a question with ONE card and
ONE keyword, instead of requiring two keywords?

Why it exists (3.11.0 triage): eval-020 is a granularity miss whose gold
(383.3.d) never reaches the RAG context, and the routed bucket has PERFECT
coverage (12/12) because a routed query is answered over the whole rulebook.
eval-020 sits one keyword short of the bar: card_count=1, keyword_count=1
against `card_count >= 2 or (card_count >= 1 and keyword_count >= 2)`.

CONTROL   = is_hard_query as shipped.
TREATMENT = the same, with the card+keyword branch relaxed to keyword_count >= 1.
The card requirement STAYS. routing.py's docstring is explicit about why: the
keyword vocabulary holds everyday words (draw, discard, token, combat), so any
card-less relaxation would ship easy questions to the 60s thinking model.

Two costs this probe reports, because routing is not free:
  * COVERAGE — a newly-routed question swaps its retrieved context for
    `build_stuffed_chunks`, which is detected card sections + the rulebook. It
    carries NO errata, FAQ, patch_notes or tournament_rules chunks. A question
    whose gold lives in one of those LOSES it by routing. That is the real trap
    here, and it is why the gate is per-ref rather than aggregate.
  * QUOTA/LATENCY — every newly-routed question moves to gemini-3.5-flash
    (~25-35s, ~20 req/day free tier). Measured over the WHOLE eval set (40), not
    just the 26 evaluable, because this cost lands on every question.

PRE-COMMITTED GATE (fixed before the first run, per plan 3.11.1):
  WIN iff eval-020 gains 383.3.d AND no other question loses a gold ref.
  The newly-routed count is reported as a cost for a human to weigh, NOT as an
  automatic fail — but a win that routes half the set is a decision, not a ship.

Usage (from backend/):
    python -m scripts.routing_threshold_probe

Requires: DATABASE_URL + corpus ingestado. Does NOT require any LLM API key.
"""
import json
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
from app.rag.routing import build_stuffed_chunks, is_hard_query
from scripts.eval_judge import _parse_refs
from scripts.family_nomination_probe import gained_refs, lost_refs
from scripts.retrieval_probe import (
    _NoHydeProvider,
    _resolve_corpus_version,
    fully_covered,
    per_ref_ranks,
)

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_routing_threshold_probe.py)
# ---------------------------------------------------------------------------

def is_hard_query_relaxed(*, card_count: int, keyword_count: int) -> bool:
    """TREATMENT's classifier: production's is_hard_query with relaxed=True.

    This was a hand-written copy when the probe was the GATE that justified the
    parameter — routing.py had no relaxed branch to call yet. Now that it does,
    keeping the copy would mean measuring a treatment production may no longer
    implement (retune the branch in routing.py and the probe would happily keep
    reporting the old predicate's 3W/0L). Pinned by
    tests/test_routing_threshold_probe.py::test_treatment_is_productions_relaxed_branch.

    The `card_count >= 1` requirement lives in routing.py and is deliberate: the
    keyword vocabulary is full of everyday words, so dropping the card is how you
    accidentally route "when do I draw?".
    """
    return is_hard_query(card_count=card_count, keyword_count=keyword_count, relaxed=True)


# ---------------------------------------------------------------------------
# DB-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_all(difficulty=None) -> list[dict]:
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


def _context_for(routed, question, base_question, embedder, pool, settings,
                 corpus_version, entities, embedding, provider):
    if routed:
        stuffed = build_stuffed_chunks(base_question, known_keywords=_KNOWN_KEYWORDS)
        if stuffed is not None:
            return stuffed
        # Production degrades to the RAG path when stuffing is unavailable.
    context, _, _, _, _ = _retrieve(
        question, embedder, pool, provider, settings, None, corpus_version,
        "probe", question_embedding=embedding, entities=entities, skip_hyde=True,
    )
    return context


def run_probe(questions, embedder, pool, corpus_version, settings) -> list[dict]:
    provider = _NoHydeProvider()
    routing_enabled = settings.hard_query_routing
    results = []
    for q in questions:
        question = q["question"]
        clean_question, _ = _extract_tags(question)
        base_question = clean_question or question
        embedding = embedder.encode(base_question)
        entities = _detect_entities(base_question, pool, corpus_version, "probe")
        cc = entities.card_count([])
        kc = len(_detect_keywords(base_question))

        control_routed = routing_enabled and is_hard_query(card_count=cc, keyword_count=kc)
        treat_routed = routing_enabled and is_hard_query_relaxed(card_count=cc, keyword_count=kc)

        record = {
            "id": q.get("id", "?"),
            "card_count": cc,
            "keyword_count": kc,
            "keywords": _detect_keywords(base_question),
            "control_routed": control_routed,
            "treatment_routed": treat_routed,
            "newly_routed": treat_routed and not control_routed,
            "rule_reference": q.get("rule_reference"),
        }

        # Coverage only means something where a gold ref exists.
        if q.get("rule_reference"):
            refs = _parse_refs(q["rule_reference"])
            control_ctx = _context_for(control_routed, question, base_question, embedder,
                                       pool, settings, corpus_version, entities, embedding, provider)
            if treat_routed == control_routed:
                treat_ctx = control_ctx  # identical path — no need to pay for it twice
            else:
                treat_ctx = _context_for(treat_routed, question, base_question, embedder,
                                         pool, settings, corpus_version, entities, embedding, provider)
            record["control_per_ref"] = per_ref_ranks(refs, control_ctx)
            record["treatment_per_ref"] = per_ref_ranks(refs, treat_ctx)
        results.append(record)
    return results


def _print_report(results: list[dict]) -> None:
    evaluable = [r for r in results if "control_per_ref" in r]
    newly = [r for r in results if r["newly_routed"]]
    ctrl_routed = [r for r in results if r["control_routed"]]
    treat_routed = [r for r in results if r["treatment_routed"]]

    print("\n" + "=" * 72)
    print("ROUTING-THRESHOLD PROBE — 3.11.1 lever (a)")
    print("=" * 72)
    print(f"  questions          : {len(results)}  ({len(evaluable)} evaluable)")
    print(f"  routed CONTROL     : {len(ctrl_routed)}/{len(results)}")
    print(f"  routed TREATMENT   : {len(treat_routed)}/{len(results)}")

    gained = [(r["id"], g) for r in evaluable
              if (g := gained_refs(r["control_per_ref"], r["treatment_per_ref"]))]
    lost = [(r["id"], l) for r in evaluable
            if (l := lost_refs(r["control_per_ref"], r["treatment_per_ref"]))]

    print("\n  --- GATE ---")
    print(f"  GAINED refs : {len(gained)} questions")
    for qid, refs in gained:
        print(f"    + {qid:10s} {', '.join(refs)}")
    print(f"  LOST refs   : {len(lost)} questions")
    for qid, refs in lost:
        print(f"    - {qid:10s} {', '.join(refs)}")

    c_full = sum(1 for r in evaluable if fully_covered(r["control_per_ref"]))
    t_full = sum(1 for r in evaluable if fully_covered(r["treatment_per_ref"]))
    print(f"\n  fully-covered: CONTROL {c_full}/{len(evaluable)} "
          f"-> TREATMENT {t_full}/{len(evaluable)}")

    print("\n  --- COST: newly routed (thinking model, ~25-35s, ~20 req/day) ---")
    print(f"  newly routed: {len(newly)}/{len(results)} questions "
          f"({len(newly) / len(results) * 100:.0f}% of the set)")
    for r in newly:
        gold = r["rule_reference"] or "(no gold)"
        print(f"    {r['id']:10s} cards={r['card_count']} kw={r['keyword_count']} "
              f"{r['keywords']}  gold={gold}")
    print("=" * 72)


def main() -> None:
    print("Loading eval questions...")
    questions = _load_all()
    print(f"  {len(questions)} questions.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")
    print(f"  hard_query_routing = {settings.hard_query_routing}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    print("  Embedder ready.\n")

    try:
        results = run_probe(questions, embedder, pool, corpus_version, settings)
    finally:
        close_pool(pool)

    _print_report(results)


if __name__ == "__main__":
    main()
