"""Semantic-cache threshold calibration — deterministic, no LLM.

Why this exists: the semantic cache (plan 2.3) reuses the answer of the nearest
already-answered question. Its ONE dangerous failure is a false positive —
serving the answer to a DIFFERENT question. The only thing standing between us
and that is the cosine threshold, so the threshold must be MEASURED, not guessed.

Two numbers bound it:

  * CEILING — the highest cosine between two DIFFERENT eval questions. Any
    threshold at or below it produces a false positive on our own eval set.
  * FLOOR — the lowest cosine between a question and a hand-written paraphrase
    of ITSELF. Any threshold above it stops the cache hitting the very
    rewordings it exists to catch.

A usable threshold needs CEILING < FLOOR. This probe reports that band twice:

  ALL QUESTIONS  -> the band is EMPTY. Ceiling 0.982 (eval-013 vs eval-014:
                    "on my own turn" vs "during my opponent's turn" — two words
                    apart, OPPOSITE rulings, because 383.3.d.1 hangs the answer
                    on who the turn player is) sits ABOVE the 0.874 paraphrase
                    floor. No threshold is both safe and useful. This is why the
                    feature cannot be enabled globally.

  NON-HARD ONLY  -> the band is WIDE. Excluding questions is_hard_query() routes,
                    the ceiling collapses to ~0.763 against the same floor.
                    Rules questions hinge on discriminative micro-details (whose
                    turn, which zone, ready vs exhausted) that embeddings smooth
                    over — and those details are exactly what makes a question
                    hard. So the hard classifier doubles as the cache's safety
                    gate (see pipeline._semantic_cache_is_safe).

Usage (from backend/):
    python -m scripts.semantic_cache_probe

Requires: DB (for the card vocabulary used by the hard classifier) + the local
embedder. Costs zero LLM tokens.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.card_detect import detect_card_mentions, detect_champion_mentions, load_card_names
from app.rag.embedder import Embedder
from app.rag.pipeline import _KNOWN_KEYWORDS, _detect_keywords
from app.rag.routing import is_hard_query, load_champion_tag_index

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

# Hand-written rewordings of real eval questions — the SAME question a player
# would type differently. These are what the cache must still hit; they are the
# reason the threshold cannot simply be pushed to 0.99 "to be safe".
_PARAPHRASES: list[tuple[str, str]] = [
    (
        "How many copies of the same card can I include in my main deck?",
        "What's the maximum number of copies of one card I can put in my main deck?",
    ),
    (
        "When is damage removed from units?",
        "At what point does damage get healed off my units?",
    ),
    (
        "How many banish zones does the game have? If a spell banishes a card, where does it go?",
        "Does the game have one shared banish zone or several, and where do banished cards end up?",
    ),
    (
        "Does the Challenge spell create a showdown? Does the unit have to be able to attack?",
        "Is a showdown created by the Challenge spell, and must the unit be able to attack?",
    ),
]


def _cosine(a: list[float], b: list[float]) -> float:
    """The embedder L2-normalizes, so the dot product IS the cosine."""
    return sum(x * y for x, y in zip(a, b))


def _load_questions() -> list[dict]:
    data = json.loads(_EVAL_SET.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) and "questions" in data else data


def _is_hard(question: str, pool, corpus_version: str) -> bool:
    """The SAME classifier the pipeline gates on — not a re-implementation."""
    vocab = load_card_names(pool, corpus_version)
    cards = detect_card_mentions(question, vocab, known_keywords=_KNOWN_KEYWORDS)
    resolved, ambiguous = detect_champion_mentions(
        question, load_champion_tag_index(), known_keywords=_KNOWN_KEYWORDS
    )
    card_count = len({c.lower() for c in cards} | {c.lower() for c in resolved}) + ambiguous
    return is_hard_query(card_count=card_count, keyword_count=len(_detect_keywords(question)))


def _ceiling(questions: list[dict], vectors: dict[str, list[float]]) -> list[tuple[float, str, str]]:
    """All different-question pairs, most similar first."""
    pairs: list[tuple[float, str, str]] = []
    ids = [q["id"] for q in questions]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pairs.append((_cosine(vectors[ids[i]], vectors[ids[j]]), ids[i], ids[j]))
    pairs.sort(reverse=True)
    return pairs


def _report(label: str, pairs: list[tuple[float, str, str]], floor: float, n: int) -> float:
    print(f"\n  {label}  (n={n})")
    if not pairs:
        print("    (no pairs)")
        return 0.0
    print("    most similar DIFFERENT questions:")
    for sim, a, b in pairs[:3]:
        print(f"      {sim:.4f}  {a} vs {b}")
    ceiling = pairs[0][0]
    band = "EMPTY — no safe threshold exists" if ceiling >= floor else f"({ceiling:.4f}, {floor:.4f}]"
    print(f"    ceiling {ceiling:.4f}  vs  floor {floor:.4f}   ->  SAFE BAND: {band}")
    return ceiling


def main() -> None:
    settings = Settings()
    questions = _load_questions()
    pool = init_pool(settings.database_url, minconn=1, maxconn=2)
    try:
        corpus_version = settings.corpus_version or "v2.2.1"
        print(f"Loading embedder ({settings.model_name}) — takes ~5-10s...")
        embedder = Embedder.load(settings.model_name)

        vectors = {q["id"]: embedder.encode(q["question"]) for q in questions}
        para_sims = sorted(
            (_cosine(embedder.encode(orig), embedder.encode(para)), orig)
            for orig, para in _PARAPHRASES
        )
        floor = para_sims[0][0]

        hard = [q for q in questions if _is_hard(q["question"], pool, corpus_version)]
        soft = [q for q in questions if q not in hard]

        print("\n" + "=" * 70)
        print("SEMANTIC CACHE THRESHOLD CALIBRATION (deterministic — no LLM)")
        print("=" * 70)

        print("\n  Least similar SELF-paraphrases (these set the FLOOR):")
        for sim, orig in para_sims[:3]:
            print(f"    {sim:.4f}  {orig[:56]}...")

        _report("ALL QUESTIONS", _ceiling(questions, vectors), floor, len(questions))
        soft_ceiling = _report(
            "NON-HARD ONLY (what the cache actually serves)",
            _ceiling(soft, vectors), floor, len(soft),
        )
        print(f"\n  ({len(hard)} hard questions excluded — never semantic-cached.)")

        configured = settings.semantic_cache_threshold
        print("\n  " + "-" * 66)
        print(f"  Configured semantic_cache_threshold: {configured:.4f}")
        if soft_ceiling >= floor:
            print("  VERDICT: even the non-hard band is empty. Keep the cache OFF.")
            sys.exit(1)
        if configured <= soft_ceiling:
            print(f"  ** WARNING: {configured:.4f} is AT OR BELOW the non-hard ceiling")
            print(f"  ** ({soft_ceiling:.4f}). It would serve a wrong answer. RAISE IT.")
            sys.exit(1)
        if configured > floor:
            print(f"  NOTE: {configured:.4f} is above the paraphrase floor — safe, but it")
            print("  will miss the weakest rewordings (lower hit rate).")
        else:
            print(f"  OK: {configured:.4f} sits inside the safe band.")
        print("=" * 70)
    finally:
        close_pool(pool)


if __name__ == "__main__":
    main()
