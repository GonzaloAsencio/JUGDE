"""Auto-detect card names mentioned in a free-text question.

Why this exists: multi-card interaction questions ("I play X, opponent controls
Y, does Z happen?") embed poorly — the cosine query is dominated by the scenario
prose, so the named CARDS rarely surface in semantic retrieval. A deterministic
probe over the eval's hard bucket found 9/12 named cards ABSENT from the context
the generator sees. The cards exist in the corpus and tagged_lookup already finds
them by name; the only missing piece is spotting the names in the question and
feeding them to that lookup with reserved context slots.

The risk is FALSE POSITIVES: many single-word card names ("Charm", "Block",
"Eclipse") are also ordinary English. The matching rules below keep those quiet
unless they appear as a capitalized proper noun, while always accepting the
distinctive multi-word names.
"""
import re
from collections.abc import Iterable

from app.db import get_conn

_DEFAULT_MAX_MENTIONS = 6
# Single-word names shorter than this are too collision-prone to trust
# ("Cull", "Gust", "Defy" are real cards but also fire on incidental prose).
_MIN_SINGLE_WORD_LEN = 5

_CARD_NAME_CACHE: dict[str, tuple[str, ...]] = {}


def _is_eligible(name: str, known_keywords: frozenset[str]) -> bool:
    """Multi-word names are distinctive enough to always trust. Single-word names
    must clear a length floor and not collide with a known rules keyword (a card
    named "Counter" must not hijack a question about the counter game action)."""
    if len(name.split()) > 1:
        return True
    return len(name) >= _MIN_SINGLE_WORD_LEN and name.lower() not in known_keywords


def detect_card_mentions(
    question: str,
    card_names: Iterable[str],
    *,
    known_keywords: frozenset[str] = frozenset(),
    max_mentions: int = _DEFAULT_MAX_MENTIONS,
) -> list[str]:
    """Return card names from *card_names* that appear in *question*.

    Whole-word, case-insensitive. Longest names claim their span first so
    "Jhin Virtuoso" suppresses a contained bare "Jhin". Single-word names are
    accepted only when they occur CAPITALIZED (a proper-noun signal), keeping
    everyday words like "charm"/"block" from pulling same-named cards. Results
    are ordered by first appearance, deduped, and capped at *max_mentions*.
    """
    if not question or not card_names:
        return []

    # Longest first (by word count, then length) so a longer name claims its
    # span before any shorter name nested inside it.
    ordered = sorted(card_names, key=lambda n: (len(n.split()), len(n)), reverse=True)

    accepted_spans: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []

    for name in ordered:
        if not _is_eligible(name, known_keywords):
            continue
        single = len(name.split()) == 1
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(question):
            if single and not m.group()[0].isupper():
                continue
            if any(s <= m.start() and m.end() <= e for s, e in accepted_spans):
                continue  # nested inside an already-claimed longer name
            accepted_spans.append((m.start(), m.end()))
            hits.append((m.start(), name))
            break

    hits.sort(key=lambda t: t[0])
    out: list[str] = []
    for _, name in hits:
        if name not in out:
            out.append(name)
        if len(out) >= max_mentions:
            break
    return out


def load_card_names(pool, corpus_version: str) -> tuple[str, ...]:
    """Distinct card-name vocabulary for a corpus version (the card chunks'
    section headers, which hold the card name). Cached per corpus_version — the
    vocabulary is fixed for a given corpus, so we query the DB once."""
    cached = _CARD_NAME_CACHE.get(corpus_version)
    if cached is not None:
        return cached
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT section FROM corpus_chunks "
                "WHERE source_type = 'card' AND corpus_version = %s",
                (corpus_version,),
            )
            names = tuple(row[0] for row in cur.fetchall() if row[0])
    _CARD_NAME_CACHE[corpus_version] = names
    return names
