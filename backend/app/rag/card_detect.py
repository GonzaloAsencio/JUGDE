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
from collections import defaultdict
from collections.abc import Iterable
from functools import lru_cache

from app.db import get_conn
from app.rag.retrieval import _VARIANT_SUFFIX_RE

_DEFAULT_MAX_MENTIONS = 6
# Single-word names shorter than this are too collision-prone to trust
# ("Cull", "Gust", "Defy" are real cards but also fire on incidental prose).
_MIN_SINGLE_WORD_LEN = 5
# v2 secondary pass: a multi-token card matches when all its tokens occur,
# capitalized, within this many words of each other. 4 catches a champion +
# subtitle split by one filler word ("Irelia Legend's Blade Dancer") and a
# reversed pair ("Angel Guardian"), while rejecting tokens scattered across a
# long sentence (incidental co-occurrence).
_SUBSET_WINDOW = 4
_WORD_RE = re.compile(r"[A-Za-z0-9']+")

_CARD_NAME_CACHE: dict[str, tuple[str, ...]] = {}


def _name_tokens(name: str) -> set[str]:
    """Significant tokens of a card name: variant suffix dropped, lowercased,
    short connective tokens removed (mirrors the probe's normalisation)."""
    name = _VARIANT_SUFFIX_RE.sub("", name).lower()
    return {t for t in re.split(r"[^a-z0-9]+", name) if len(t) > 2}


def _norm_word(word: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", word.lower())


def _capitalized_positions(words: list[tuple[str, int]], tokens: set[str]) -> dict[str, list[int]]:
    """Word indices where each *token* appears CAPITALIZED in *words*.

    Only capitalized occurrences count — the proper-noun signal that keeps an
    everyday lowercase use of a card-name word from contributing to a match.
    """
    pos: dict[str, list[int]] = {}
    for i, (word, _) in enumerate(words):
        if not word[:1].isupper():
            continue
        nw = _norm_word(word)
        if nw in tokens:
            pos.setdefault(nw, []).append(i)
    return pos


def _min_window_start(positions_by_token: dict[str, list[int]], window: int) -> int | None:
    """Smallest word index of a span covering one occurrence of every token
    within *window* words (min-window-substring). None if no such span exists."""
    events = sorted((p, tok) for tok, ps in positions_by_token.items() for p in ps)
    need = len(positions_by_token)
    count: dict[str, int] = defaultdict(int)
    distinct = 0
    left = 0
    for right in range(len(events)):
        count[events[right][1]] += 1
        if count[events[right][1]] == 1:
            distinct += 1
        while distinct == need:
            if events[right][0] - events[left][0] <= window:
                return events[left][0]
            count[events[left][1]] -= 1
            if count[events[left][1]] == 0:
                distinct -= 1
            left += 1
    return None


def _is_eligible(name: str, known_keywords: frozenset[str]) -> bool:
    """Multi-word names are distinctive enough to always trust. Single-word names
    must clear a length floor and not collide with a known rules keyword (a card
    named "Counter" must not hijack a question about the counter game action)."""
    if len(name.split()) > 1:
        return True
    return len(name) >= _MIN_SINGLE_WORD_LEN and name.lower() not in known_keywords


@lru_cache(maxsize=16)
def _prepare_vocab(
    card_names: tuple[str, ...], known_keywords: frozenset[str]
) -> tuple[tuple, tuple]:
    """Precompute, once per (vocabulary, keywords), everything detect_card_mentions
    needs per request: the eligible names ordered longest-first with their
    compiled whole-word patterns, and the multi-token names with their token sets
    for the secondary pass.

    Compiling a regex for every card name on every request was O(N_cards) CPU on
    the hot path; the vocabulary is fixed per corpus, so this is cached. Keyed on
    the (hashable) names tuple + keywords frozenset.
    """
    # Longest first (by word count, then length) so a longer name claims its
    # span before any shorter name nested inside it.
    ordered = sorted(card_names, key=lambda n: (len(n.split()), len(n)), reverse=True)

    exact: list[tuple[str, "re.Pattern[str]", bool]] = []
    for name in ordered:
        if not _is_eligible(name, known_keywords):
            continue
        single = len(name.split()) == 1
        pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
        exact.append((name, pattern, single))

    subset: list[tuple[str, frozenset[str]]] = []
    for name in ordered:
        tokens = _name_tokens(name)
        if len(tokens) >= 2:
            subset.append((name, frozenset(tokens)))

    return tuple(exact), tuple(subset)


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

    exact, subset = _prepare_vocab(tuple(card_names), known_keywords)

    accepted_spans: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []

    for name, pattern, single in exact:
        for m in pattern.finditer(question):
            if single and not m.group()[0].isupper():
                continue
            if any(s <= m.start() and m.end() <= e for s, e in accepted_spans):
                continue  # nested inside an already-claimed longer name
            accepted_spans.append((m.start(), m.end()))
            hits.append((m.start(), name))
            break

    # Secondary pass: window-bounded token-subset match for multi-token names the
    # exact-phrase pass missed — reversed order ("Angel Guardian" -> "Guardian
    # Angel") or tokens split by filler ("Irelia Legend's Blade Dancer" -> "Irelia
    # Blade Dancer"). Capitalization + a short window guard against false positives.
    matched = {name for _, name in hits}
    indexed = [(m.group(), m.start()) for m in _WORD_RE.finditer(question)]
    for name, tokens in subset:
        if name in matched:
            continue
        positions = _capitalized_positions(indexed, tokens)
        if len(positions) < len(tokens):
            continue  # some token never appears capitalized
        start_idx = _min_window_start(positions, _SUBSET_WINDOW)
        if start_idx is None:
            continue
        hits.append((indexed[start_idx][1], name))
        matched.add(name)

    hits.sort(key=lambda t: t[0])
    out: list[str] = []
    for _, name in hits:
        if name not in out:
            out.append(name)
        if len(out) >= max_mentions:
            break
    return out


def detect_champion_mentions(
    question: str,
    tag_index: dict[str, tuple[str, ...]],
    *,
    known_keywords: frozenset[str] = frozenset(),
) -> tuple[list[str], int]:
    """Resolve bare champion identity mentions ("a Vi", "I play Ahri") that
    :func:`detect_card_mentions` cannot see — the card vocabulary only holds
    full printed names ("Vi Piltover Enforcer", "Vi Destructive", ...), never
    the bare champion name a player actually types.

    *tag_index* maps a lowercased champion tag to every printed card that
    carries it (see ``routing.load_champion_tag_index``) — curated ground
    truth from each card's ``Type: Legend`` block, not a raw first-word guess.

    Returns ``(resolved_names, ambiguous_count)``:
    - A tag with exactly ONE card is unambiguous: that card's full name is
      returned in *resolved_names*, safe to treat like any other exact card
      match.
    - A tag with multiple printed cards (e.g. "Vi" has 7) is ambiguous: we
      never guess which one is meant — no name is added — but the mention
      still counts as evidence of a multi-entity question, tallied in
      *ambiguous_count* so callers can factor it into routing decisions
      without asserting a card identity.

    Same proper-noun signal as the single-word pass in
    :func:`detect_card_mentions`: a tag only counts when it appears
    CAPITALIZED, and tags colliding with a known rules keyword are skipped.
    No length floor — the vocabulary is pre-vetted, not a raw word guess.
    """
    if not question or not tag_index:
        return [], 0

    # Longest tag first (word count, then length) so "Master Yi" claims its
    # span before a shorter tag could nest inside it — mirrors _prepare_vocab.
    ordered_tags = sorted(
        tag_index, key=lambda t: (len(t.split()), len(t)), reverse=True
    )

    accepted_spans: list[tuple[int, int]] = []
    hits: list[tuple[int, str]] = []
    for tag in ordered_tags:
        if tag in known_keywords:
            continue
        pattern = re.compile(r"\b" + re.escape(tag) + r"\b", re.IGNORECASE)
        for m in pattern.finditer(question):
            if not m.group()[0].isupper():
                continue
            if any(s <= m.start() and m.end() <= e for s, e in accepted_spans):
                continue  # nested inside an already-claimed longer tag
            accepted_spans.append((m.start(), m.end()))
            hits.append((m.start(), tag))
            break

    hits.sort(key=lambda t: t[0])
    resolved: list[str] = []
    ambiguous_count = 0
    for _, tag in hits:
        names = tag_index[tag]
        if len(names) == 1:
            if names[0] not in resolved:
                resolved.append(names[0])
        else:
            ambiguous_count += 1
    return resolved, ambiguous_count


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
