"""Card-presence probe — deterministic (no LLM) guard for the entity-aware card
retrieval fix. Measures the fix's contract: every card NAME detected in a question
must land in the final context the generator sees.

Why this exists: multi-card interaction questions embed poorly (the scenario prose
dominates the cosine), so named cards rarely surface in semantic retrieval. The fix
auto-detects card names and feeds them to tagged_lookup with reserved slots. This
probe reports, per question, which detected cards made it into context. A delivery
rate below ~100% means the assembly/budget regressed. It also prints the cards
actually retrieved so a human can eyeball detector MISSES (cards named but not
detected) without a hand-maintained gold map.

Routing awareness (2026-07-16 — the guard had a coverage hole): this probe used to
re-implement the retrieval path and, in doing so, never modelled hard-query
routing. 15 of the 21 hard questions ROUTE, and a routed query throws the whole
retrieved context away (`chunks = stuffed`, pipeline.py:699). So for 71% of its
own bucket the guard was measuring a context production discards, and was blind to
whether the path those questions actually use — the stuffed context — delivers the
cards at all. It reported a confident 100% while watching the wrong door.

It now resolves the real path per question and measures presence in the context
production would ACTUALLY build:

  * routed     -> build_stuffed_chunks (which does its own card detection and
                  puts the detected card sections FIRST)
  * not routed -> _retrieve (the real assembly, HyDE off)

Calling the pipeline instead of re-implementing it is the point: the previous
version drifted from production precisely because it kept its own copy of the
assembly. Same lesson as scripts/retrieval_probe.py — see docs/improvement-plan.md
Fase 6.

Usage (from backend/):
    PYTHONPATH=. TOP_K=10 python -m scripts.card_presence_probe
    python -m scripts.card_presence_probe --difficulty medium

Requires: DATABASE_URL + corpus ingestado. Does NOT require any LLM API key.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, get_conn, init_pool
from app.rag.card_detect import load_card_names
from app.rag.embedder import Embedder
from app.rag.pipeline import (
    _KNOWN_KEYWORDS,
    _detect_entities,
    _detect_keywords,
    _extract_tags,
    _retrieve,
)
from app.rag.retrieval import _CARD_NAME_RE, _VARIANT_SUFFIX_RE
from app.rag.routing import build_stuffed_chunks
# Reuse rather than redefine: "would production route this?" must have exactly ONE
# answer in this repo, or the two probes drift apart and we are back where we
# started. Same for the bucket split.
from scripts.retrieval_probe import _NoHydeProvider, routing_decision, split_by_route

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_card_presence_probe.py — no DB, no LLM)
# ---------------------------------------------------------------------------

def card_name_of(chunk) -> str | None:
    """Parse the **Name** of a card chunk; None for non-cards or cards without a
    parseable name. Mirrors how retrieval._printing_key reads the card identity."""
    if chunk.source_type != "card":
        return None
    match = _CARD_NAME_RE.search(chunk.content)
    return match.group(1).strip() if match else None


def _norm_tokens(name: str) -> set[str]:
    """Normalised content tokens of a card name: variant suffix dropped, lowercased,
    short connective tokens removed. Used for order-tolerant name comparison."""
    name = _VARIANT_SUFFIX_RE.sub("", name).lower()
    return {t for t in re.split(r"[^a-z0-9]+", name) if len(t) > 2}


def card_present(name: str, chunks) -> bool:
    """True if some CARD chunk in *chunks* is the card *name* — matched by token
    subset so "Vex Apathetic" finds "Vex - Apathetic" and variant suffixes are
    ignored. Non-card chunks never count, even if they mention the name."""
    want = _norm_tokens(name)
    if not want:
        return False
    for chunk in chunks:
        nm = card_name_of(chunk)
        if nm and want.issubset(_norm_tokens(nm)):
            return True
    return False


def delivery_rate(records: list[dict]) -> dict:
    """Aggregate detected/present counts across per-question records.

    Each record has "detected" and "present" (lists of card names). Returns total
    detected, total delivered, the delivery rate (delivered/detected, 0.0 when none
    detected — no division error), and how many questions named no detectable card.
    """
    detected = sum(len(r["detected"]) for r in records)
    present = sum(len(r["present"]) for r in records)
    no_card = sum(1 for r in records if not r["detected"])
    return {
        "detected": detected,
        "present": present,
        "rate": present / detected if detected else 0.0,
        "no_card_questions": no_card,
    }


# ---------------------------------------------------------------------------
# DB-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

def _load_questions(difficulty: str | None) -> list[dict]:
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    questions = data["questions"] if isinstance(data, dict) and "questions" in data else data
    if difficulty:
        questions = [q for q in questions if q.get("difficulty") == difficulty]
    return questions


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


def reproduce_context(question, embedder, pool, settings, corpus_version, *, routing_enabled):
    """Build the context production would ACTUALLY give the generator.

    Resolves the real path (routed vs not) through the same gate production
    uses, then defers to the real pipeline for the context itself — no local
    copy of the assembly, because that copy is what drifted last time.
    Returns (detected_card_tags, context_chunks, routed).
    """
    # Production detects on the tag-stripped question (pipeline.py:377-383).
    clean_question, _ = _extract_tags(question)
    base_question = clean_question or question

    entities = _detect_entities(base_question, pool, corpus_version, "probe")
    detected_tags = list(dict.fromkeys(entities.auto_card_tags))
    routed = routing_decision(
        card_count=entities.card_count([]),
        keyword_count=len(_detect_keywords(base_question)),
        routing_enabled=routing_enabled,
    )

    if routed:
        stuffed = build_stuffed_chunks(base_question, known_keywords=_KNOWN_KEYWORDS)
        if stuffed is not None:
            return detected_tags, stuffed, True
        # Stuffing unavailable -> production degrades to the RAG path
        # (pipeline.py:698), so the probe must too.
        routed = False

    # _retrieve takes the RAW question — it strips tags itself.
    context, _, _, _, _ = _retrieve(
        question, embedder, pool, _NoHydeProvider(), settings, None, corpus_version,
        "probe", question_embedding=embedder.encode(base_question), entities=entities,
        skip_hyde=True,
    )
    return detected_tags, context, routed


def run_probe(questions, embedder, pool, settings, corpus_version, *, routing_enabled) -> list[dict]:
    records = []
    for q in questions:
        detected_tags, ctx, routed = reproduce_context(
            q["question"], embedder, pool, settings, corpus_version,
            routing_enabled=routing_enabled,
        )
        present = [t for t in detected_tags if card_present(t, ctx)]
        retrieved = [n for n in (card_name_of(c) for c in ctx) if n]
        kinds: dict[str, int] = {}
        for c in ctx:
            kinds[c.source_type] = kinds.get(c.source_type, 0) + 1
        records.append({
            "id": q.get("id", "?"),
            "routed": routed,
            "detected": detected_tags,
            "present": present,
            "retrieved_cards": retrieved,
            "kinds": kinds,
        })
    return records


def _print_report(records: list[dict], difficulty: str | None, top_k: int,
                  *, routing_enabled: bool) -> None:
    agg = delivery_rate(records)
    routed, retrieved_bucket = split_by_route(records)
    print("\n" + "=" * 64)
    print("CARD-PRESENCE PROBE (deterministic — no LLM, HyDE off)")
    print("=" * 64)
    print(f"  difficulty filter : {difficulty or 'ALL'}    TOP_K={top_k}")
    print(f"  hard_query_routing: {'ON' if routing_enabled else 'OFF'}")
    print(f"  questions         : {len(records)}")
    print(f"  cards detected    : {agg['detected']}")
    print(f"  cards delivered   : {agg['present']}  (in final context)")
    print(f"  DELIVERY RATE     : {agg['rate']:.0%}  (detected cards that landed in context)")
    print(f"  no-card questions : {agg['no_card_questions']}  (named no detectable card)")

    # Split the rate by path. A blended number hides which door is leaking, and
    # these are two entirely different mechanisms: stuffing detects and prepends
    # its own card sections; the RAG path relies on tagged_lookup + reserved
    # slots in _assemble_context. A regression in either must be visible alone.
    print("\n  --- by production path (the two mechanisms are unrelated) ---")
    for label, bucket in (("routed  (stuffed)", routed), ("rag     (assembly)", retrieved_bucket)):
        if not bucket:
            print(f"  {label}: (none)")
            continue
        b = delivery_rate(bucket)
        print(f"  {label}: {b['present']}/{b['detected']} cards "
              f"({b['rate']:.0%}) over {len(bucket)} questions")

    print("\n  Per-question:")
    for r in records:
        route = "STUFFED" if r["routed"] else "rag    "
        if not r["detected"]:
            print(f"    {r['id']:10s} {route} (no cards detected)  ctx={r['kinds']}")
            continue
        missing = [t for t in r["detected"] if t not in r["present"]]
        flag = "OK " if not missing else "MISS"
        print(f"    {r['id']:10s} {route} [{flag}] detected={r['detected']} "
              f"missing={missing or '-'}")
        print(f"               retrieved cards: {r['retrieved_cards'] or '(none)'}")
    print("=" * 64)


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic card-presence probe for the entity-aware fix.")
    p.add_argument(
        "--difficulty", type=str, default="hard",
        help="Eval difficulty bucket to probe (default: hard). Pass 'all' for the whole set.",
    )
    return p.parse_args(argv)


def main() -> None:
    args = _parse_args()
    difficulty = None if args.difficulty == "all" else args.difficulty

    print(f"Loading eval questions (difficulty={difficulty or 'ALL'})...")
    questions = _load_questions(difficulty)
    print(f"  {len(questions)} questions.")

    settings = Settings()
    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    print(f"  corpus_version = {corpus_version}")

    print("Loading embedder (takes ~5-10s)...")
    embedder = Embedder.load(settings.model_name)
    vocab = load_card_names(pool, corpus_version)
    print(f"  Embedder ready. Card vocabulary: {len(vocab)} names.")

    # Read the real flag: the probe must classify questions the way the running
    # deployment does, not the way we remember it being configured.
    routing_enabled = settings.hard_query_routing
    print(f"  hard_query_routing = {routing_enabled}\n")

    try:
        records = run_probe(
            questions, embedder, pool, settings, corpus_version,
            routing_enabled=routing_enabled,
        )
    finally:
        close_pool(pool)

    _print_report(records, difficulty, settings.top_k, routing_enabled=routing_enabled)


if __name__ == "__main__":
    main()
