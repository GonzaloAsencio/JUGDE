"""Hard-query routing: deterministic classifier + full-rulebook stuffed context.

Improvement plan 4.2 + 4.3. The residual hard-bucket misses (eval-014/015/017/
019) are multi-entity questions whose gold rules no retrieval expansion
reaches; the 2026-07-12 probes showed (a) stuffing the ENTIRE rulebook into
the context makes them answerable by definition, and (b) two of them
additionally need a thinking model to bridge the rules (flash-lite reads
383.3.d and still answers "it depends"; gemini-3.5-flash applies 383.3.d.1).

This module owns the two deterministic halves — classifying a query as hard
(zero LLM calls) and assembling the stuffed context from the data files that
ship with the deploy. Model selection lives in Settings/provider wiring.
"""
import re
from functools import lru_cache
from pathlib import Path

from app.observability import get_logger
from app.rag.card_detect import detect_card_mentions
from app.rag.retrieval import Chunk

logger = get_logger(__name__)

# backend/data/processed — anchored to this file, not the CWD: the app boots
# from / in some environments and from backend/ in others.
_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"

RULEBOOK_CHUNK_ID = "rulebook:full"

_CARD_HEADER = re.compile(r"^## (.+)$", re.MULTILINE)


def is_hard_query(*, card_count: int, keyword_count: int) -> bool:
    """Deterministic hard classifier — no LLM, no I/O.

    Thresholds calibrated on the annotated eval set (2026-07-12): cards >= 2
    OR (a card plus >= 2 keywords) routes all 4 residual misses plus 10 more
    hard/medium questions and zero easy ones. The keyword signal alone is NOT
    enough: the keyword vocabulary contains everyday words (draw, discard,
    token, combat), so a card-less rule like "keywords >= 2" would send easy
    questions ("when do I draw and when do I discard?") to the 60s thinking
    model — and on the eval set every 0-card question has at most 1 keyword,
    so requiring the card costs no target coverage. Question length was also
    evaluated and rejected (no additional targets, more over-routing).
    """
    return card_count >= 2 or (card_count >= 1 and keyword_count >= 2)


@lru_cache(maxsize=1)
def _load_rulebook() -> str:
    return (_PROCESSED_DIR / "rulebook.md").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _load_card_sections() -> dict[str, str]:
    """cards.md split by '## <card name>' headers -> {name: section text}.
    Cached once; callers must treat the dict as read-only."""
    text = (_PROCESSED_DIR / "cards.md").read_text(encoding="utf-8")
    matches = list(_CARD_HEADER.finditer(text))
    sections: dict[str, str] = {}
    for m, nxt in zip(matches, matches[1:] + [None]):
        end = nxt.start() if nxt else len(text)
        sections[m.group(1).strip()] = text[m.start():end].strip()
    return sections


def build_stuffed_chunks(
    question: str,
    *,
    known_keywords: frozenset[str],
    extra_card_names: tuple[str, ...] = (),
) -> list[Chunk] | None:
    """Stuffed context for a routed query: detected card sections first
    (mirrors production's explicit-chunk ordering), the whole rulebook last.

    Card detection runs against the cards.md vocabulary — the same file the
    card chunks were ingested from — so the routed context matches what the
    probe validated, with no DB dependency. *extra_card_names* carries cards
    the caller already knows about beyond the question prose (the request's
    card_mentions): a terse question plus explicit mentions can classify as
    hard, and the very cards that triggered routing must reach the context.

    Never-raise: on any data-file problem the caller falls back to the normal
    RAG path instead of failing the query.
    """
    try:
        cards = _load_card_sections()
        rulebook = _load_rulebook()
    except Exception as e:
        logger.warning("routing.stuffing_unavailable", error=str(e))
        return None

    mentions = detect_card_mentions(question, cards.keys(), known_keywords=known_keywords)
    seen = {m.lower() for m in mentions}
    by_lower = {name.lower(): name for name in cards}
    for extra in extra_card_names:
        name = by_lower.get(extra.strip().lower())
        if name and name.lower() not in seen:
            mentions.append(name)
            seen.add(name.lower())
    chunks = [
        Chunk(id=f"card:{name}", content=cards[name], section=name,
              parent_section=None, source_type="card", similarity=1.0)
        for name in mentions
    ]
    chunks.append(Chunk(id=RULEBOOK_CHUNK_ID, content=rulebook,
                        section="Core Rulebook (complete)", parent_section=None,
                        source_type="rulebook", similarity=0.0))
    return chunks
