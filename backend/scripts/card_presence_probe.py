"""Card-presence probe — deterministic (no LLM) guard for the entity-aware card
retrieval fix. Measures the fix's contract: every card NAME detected in a question
must land in the final context the generator sees.

Why this exists: multi-card interaction questions embed poorly (the scenario prose
dominates the cosine), so named cards rarely surface in semantic retrieval. The fix
auto-detects card names and feeds them to tagged_lookup with reserved slots. This
probe reproduces the production retrieval path WITHOUT the LLM (it skips the HyDE
arm — neutral, and would only ADD cards) and reports, per question, which detected
cards made it into context. A delivery rate below ~100% means the assembly/budget
regressed. It also prints the cards actually retrieved so a human can eyeball
detector MISSES (cards named but not detected) without a hand-maintained gold map.

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
from app.rag.card_detect import detect_card_mentions, load_card_names
from app.rag.embedder import Embedder
from app.rag.pipeline import _KNOWN_KEYWORDS, _assemble_context, _detect_keywords
from app.rag.retrieval import _CARD_NAME_RE, _VARIANT_SUFFIX_RE, hybrid_search, tagged_lookup

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


def reproduce_context(question, embedder, pool, settings, corpus_version, vocab):
    """Rebuild the final context the generator would see, deterministically —
    mirrors pipeline.answer_question MINUS the HyDE arm (which calls the LLM).
    Returns (detected_card_tags, context_chunks)."""
    auto_card_tags = [
        c.lower() for c in detect_card_mentions(question, vocab, known_keywords=_KNOWN_KEYWORDS)
    ]
    directed_tags = list(dict.fromkeys(auto_card_tags))
    auto_tags = _detect_keywords(question)
    auto_only_tags = [t for t in auto_tags if t not in directed_tags]

    semantic = hybrid_search(
        pool, embedder.encode(question), question, corpus_version,
        top_k=settings.top_k, top_k_fetch=settings.top_k_fetch, rrf_k=settings.rrf_k,
    )
    explicit_chunks = tagged_lookup(pool, directed_tags, corpus_version) if directed_tags else []
    auto_chunks = tagged_lookup(pool, auto_only_tags, corpus_version) if auto_only_tags else []
    context = _assemble_context(explicit_chunks, semantic, auto_chunks, settings.top_k)
    return directed_tags, context


def run_probe(questions, embedder, pool, settings, corpus_version, vocab) -> list[dict]:
    records = []
    for q in questions:
        detected_tags, ctx = reproduce_context(
            q["question"], embedder, pool, settings, corpus_version, vocab
        )
        present = [t for t in detected_tags if card_present(t, ctx)]
        retrieved = [n for n in (card_name_of(c) for c in ctx) if n]
        kinds: dict[str, int] = {}
        for c in ctx:
            kinds[c.source_type] = kinds.get(c.source_type, 0) + 1
        records.append({
            "id": q.get("id", "?"),
            "detected": detected_tags,
            "present": present,
            "retrieved_cards": retrieved,
            "kinds": kinds,
        })
    return records


def _print_report(records: list[dict], difficulty: str | None, top_k: int) -> None:
    agg = delivery_rate(records)
    print("\n" + "=" * 64)
    print("CARD-PRESENCE PROBE (deterministic — no LLM)")
    print("=" * 64)
    print(f"  difficulty filter : {difficulty or 'ALL'}    TOP_K={top_k}")
    print(f"  questions         : {len(records)}")
    print(f"  cards detected    : {agg['detected']}")
    print(f"  cards delivered   : {agg['present']}  (in final context)")
    print(f"  DELIVERY RATE     : {agg['rate']:.0%}  (detected cards that landed in context)")
    print(f"  no-card questions : {agg['no_card_questions']}  (named no detectable card)")
    print("\n  Per-question:")
    for r in records:
        if not r["detected"]:
            print(f"    {r['id']:10s} (no cards detected)  ctx={r['kinds']}")
            continue
        missing = [t for t in r["detected"] if t not in r["present"]]
        flag = "OK " if not missing else "MISS"
        print(f"    {r['id']:10s} [{flag}] detected={r['detected']} "
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
    print(f"  Embedder ready. Card vocabulary: {len(vocab)} names.\n")

    try:
        records = run_probe(questions, embedder, pool, settings, corpus_version, vocab)
    finally:
        close_pool(pool)

    _print_report(records, difficulty, settings.top_k)


if __name__ == "__main__":
    main()
