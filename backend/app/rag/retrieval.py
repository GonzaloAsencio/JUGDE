import re
from dataclasses import dataclass

from psycopg2.pool import ThreadedConnectionPool

from app.db import get_conn
from app.observability import observe_or_noop


@dataclass(frozen=True)
class Chunk:
    id: str
    content: str
    section: str
    parent_section: str | None
    source_type: str
    similarity: float
    metadata: dict | None = None


_SQL = """
SELECT id, content, section, parent_section, source_type, metadata,
       1 - (embedding <=> %s::vector) AS similarity
FROM corpus_chunks
WHERE corpus_version = %s{set_clause}
ORDER BY embedding <=> %s::vector
LIMIT %s;
"""

_FTS_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', %s){set_clause}
ORDER BY ts_rank_cd(to_tsvector('simple', content), plainto_tsquery('simple', %s)) DESC
LIMIT %s;
"""

# Filtro por expansión: incluye SIEMPRE los chunks 'core' (reglas base aplican a
# todos los sets) además del set pedido. Devuelve (cláusula SQL, params).
def _set_clause(set_filter: str | None) -> tuple[str, tuple]:
    if not set_filter:
        return "", ()
    return "\n  AND (metadata->>'set' = %s OR metadata->>'set' = 'core')", (set_filter,)


def vector_search(
    pool: ThreadedConnectionPool,
    embedding: list[float],
    corpus_version: str,
    top_k: int = 5,
    set_filter: str | None = None,
) -> list[Chunk]:
    """Return top-K most similar chunks using cosine similarity on the pgvector column."""
    clause, clause_params = _set_clause(set_filter)
    sql = _SQL.format(set_clause=clause)
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (embedding, corpus_version, *clause_params, embedding, top_k))
            rows = cur.fetchall()

    return [
        Chunk(
            id=str(row[0]),
            content=row[1],
            section=row[2],
            parent_section=row[3],
            source_type=row[4],
            metadata=row[5],
            similarity=float(row[6]),
        )
        for row in rows
    ]


def fts_search(
    pool: ThreadedConnectionPool,
    query_text: str,
    corpus_version: str,
    top_k: int = 5,
    set_filter: str | None = None,
) -> list[Chunk]:
    """Full-text search over corpus_chunks using plainto_tsquery('simple', query_text).

    Returns Chunks ordered by ts_rank_cd desc. similarity is set to 0.0 because
    FTS rank is not comparable to cosine similarity. Empty query_text or zero
    matches returns [] without raising.

    NOT wired into the production path: _hybrid_search_impl fuses against an
    EMPTY fts list on purpose (see the rationale there). Kept for the future
    re-evaluation named in that comment — keyword-extracted queries.

    Reading its output correctly (measured 2026-07-16, plan 6.2 — this trips
    people up): **plainto_tsquery ANDs every term**, so a full natural-language
    question demands a chunk containing ALL of its words and matches nothing.
    That is why probes report fts recall 0% at every k over the eval set, and it
    is EXPECTED — not a broken arm. The arm itself works: short keyword queries
    return well-targeted rule sections ('banish' -> '427. Banish',
    'triggered abilities' -> '383. Triggered Abilities'). Before concluding this
    arm is dead, check what you fed it.
    """
    clause, clause_params = _set_clause(set_filter)
    sql = _FTS_SQL.format(set_clause=clause)
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (corpus_version, query_text, *clause_params, query_text, top_k))
            rows = cur.fetchall()

    return [
        Chunk(
            id=str(row[0]),
            content=row[1],
            section=row[2],
            parent_section=row[3],
            source_type=row[4],
            metadata=row[5],
            similarity=0.0,
        )
        for row in rows
    ]


# Authority chain: an errata exists to CORRECT the base rule, so when sources
# conflict the errata supersedes the rule — always. Patch notes sit between
# errata and the base rulebook. We REWARD authority (multiplier > 1.0); we never
# penalize a source. Anything not listed keeps the neutral 1.0 weight.
#
# Boost magnitude is MILD on purpose (sim_102). A stronger boost (errata 1.10,
# patch 1.05) flipped a clearly-better rulebook chunk below an errata several
# ranks behind — burying rulebook gold past the top-5 cutoff and costing 6pp
# recall@5 on the deterministic eval probe (53% vs 59% on corpus v2.1.0). At
# 1.02/1.01 errata still wins on comparable ranks (it only needs a small edge
# to break a near-tie) without displacing a rulebook chunk that genuinely ranks
# higher. See scripts/authority_boost_probe.py.
_AUTHORITY_BOOST = {
    "errata": 1.02,
    "patch_notes": 1.01,
}
_DEFAULT_BOOST = 1.0


def _authority_boost(source_type: str) -> float:
    return _AUTHORITY_BOOST.get(source_type, _DEFAULT_BOOST)


def _rrf_fuse(
    vector_results: list[Chunk],
    fts_results: list[Chunk],
    rrf_k: int,
    top_k: int,
) -> list[Chunk]:
    """Reciprocal Rank Fusion of two ranked Chunk lists.

    For each chunk d, score(d) = sum over lists l in {vector, fts} of
    1 / (rrf_k + rank_l(d)), where rank_l(d) is 1-based (only counted if d
    appears in l).

    Authoritative chunks receive an _authority_boost multiplier so errata rank
    above patch_notes, and both rank above the base rulebook, when scores are
    comparable (errata > patch_notes > rulebook).

    Dedup key: chunk.id.
    Tie-break: chunk that appeared in vector_results wins (stable).
    Preserves original similarity from vector side; FTS-only chunks keep 0.0.
    Truncates to top_k.
    """
    # Build score accumulators and canonical Chunk objects.
    # We track whether a chunk came from vector to apply tie-break.
    scores: dict[str, float] = {}
    chunks_by_id: dict[str, Chunk] = {}
    in_vector: set[str] = set()

    for rank_0, chunk in enumerate(vector_results):
        rank = rank_0 + 1  # 1-based
        boost = _authority_boost(chunk.source_type)
        scores[chunk.id] = scores.get(chunk.id, 0.0) + boost / (rrf_k + rank)
        chunks_by_id[chunk.id] = chunk  # vector side wins for Chunk object
        in_vector.add(chunk.id)

    for rank_0, chunk in enumerate(fts_results):
        rank = rank_0 + 1  # 1-based
        boost = _authority_boost(chunk.source_type)
        scores[chunk.id] = scores.get(chunk.id, 0.0) + boost / (rrf_k + rank)
        if chunk.id not in chunks_by_id:
            chunks_by_id[chunk.id] = chunk  # FTS-only: use FTS chunk (similarity=0.0)

    # Sort: descending score; tie-break: vector-side chunks first (stable)
    def sort_key(chunk_id: str) -> tuple:
        return (-scores[chunk_id], 0 if chunk_id in in_vector else 1)

    sorted_ids = sorted(scores.keys(), key=sort_key)
    return [chunks_by_id[cid] for cid in sorted_ids[:top_k]]


def fuse_results(
    primary: list[Chunk],
    secondary: list[Chunk],
    rrf_k: int = 60,
    top_k: int = 5,
) -> list[Chunk]:
    """RRF-fuse two FULL retrieval result lists with equal weight (the fuse_eq
    strategy that won the offline experiment: recall@5 41%->59%).

    Used to combine the raw-question arm with the HyDE arm. *primary* is the raw
    arm: it wins ties and owns the canonical Chunk object (its similarity is a
    real cosine), so a question that already retrieves well is never displaced by
    the HyDE arm. Authority boost (errata > patch_notes > rulebook) applies to
    both arms. Delegates to _rrf_fuse, which already implements exactly this.
    """
    return _rrf_fuse(primary, secondary, rrf_k, top_k)


# A card printed in several sets is indexed once per printing, with identical
# rules text. Their **Name** fields differ only by a trailing "(Variant)" suffix
# (e.g. "Irelia - Blade Dancer" vs "...(Metal)"). Left alone, near-identical
# printings crowd the top_k and starve a ruling of its other evidence.
_CARD_NAME_RE = re.compile(r"\*\*Name\*\*:\s*([^|*\n]+)")
_VARIANT_SUFFIX_RE = re.compile(r"\s*\([^)]*\)\s*$")


def _printing_key(chunk: Chunk) -> str | None:
    """Base-card identity for a card chunk: its **Name** minus the printing
    variant suffix, lowercased. None for non-cards or cards without a Name."""
    if chunk.source_type != "card":
        return None
    match = _CARD_NAME_RE.search(chunk.content)
    if not match:
        return None
    return _VARIANT_SUFFIX_RE.sub("", match.group(1).strip()).lower()


def _dedup_card_printings(chunks: list[Chunk]) -> list[Chunk]:
    """Drop lower-ranked printings of the same base card, keeping the first
    (highest-ranked) occurrence. Non-card chunks and cards without a parseable
    name pass through untouched, preserving order."""
    seen_keys: set[str] = set()
    out: list[Chunk] = []
    for chunk in chunks:
        key = _printing_key(chunk)
        if key is not None:
            if key in seen_keys:
                continue
            seen_keys.add(key)
        out.append(chunk)
    return out


def _hybrid_search_impl(
    pool: ThreadedConnectionPool,
    embedding: list[float],
    query_text: str,
    corpus_version: str,
    top_k: int = 5,
    top_k_fetch: int = 15,
    rrf_k: int = 60,
    set_filter: str | None = None,
) -> list[Chunk]:
    # The FTS arm is DORMANT. A deterministic probe over the eval set measured
    # vector-only @5 recall (47%) ABOVE vector+FTS (41%): plainto_tsquery over a
    # full natural-language question rarely matches rule text and only dilutes the
    # RRF ranking. We therefore fuse vector results against an EMPTY fts list —
    # which keeps the authority boost (errata > patch_notes > rulebook) intact
    # while dropping the dilution. fts_search/_FTS_SQL remain for future
    # re-evaluation (e.g. a different corpus or keyword-extracted queries).
    # query_text is retained in the signature for that future use and API stability.
    vec_results = vector_search(pool, embedding, corpus_version, top_k=top_k_fetch, set_filter=set_filter)
    # Collapse duplicate card printings BEFORE truncation so freed slots go to
    # other evidence (different cards, rules) instead of repeating one card.
    vec_results = _dedup_card_printings(vec_results)
    return _rrf_fuse(vec_results, [], rrf_k, top_k)


hybrid_search = observe_or_noop(_hybrid_search_impl, name="retrieval")


_TAGGED_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND LOWER(section) ILIKE LOWER(%s)
ORDER BY (source_type = 'card') DESC,
         (source_type = 'rulebook') DESC
LIMIT 2
"""


def tagged_lookup(
    pool: ThreadedConnectionPool,
    tags: list[str],
    corpus_version: str,
) -> list[Chunk]:
    """Direct lookup by section name. This is a lexical match (section ILIKE tag),
    not a vector search, so it computes NO cosine similarity. Chunks are returned
    with similarity=0.0 — fabricating a 1.0 here would inflate the pipeline's
    reported confidence on any query that merely matches a tag.
    """
    if not tags:
        return []
    results: list[Chunk] = []
    seen_ids: set[str] = set()
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            for tag in tags:
                cur.execute(_TAGGED_SQL, (corpus_version, f"%{tag}%"))
                for row in cur.fetchall():
                    chunk_id = str(row[0])
                    if chunk_id not in seen_ids:
                        seen_ids.add(chunk_id)
                        results.append(Chunk(
                            id=chunk_id,
                            content=row[1],
                            section=row[2],
                            parent_section=row[3],
                            source_type=row[4],
                            metadata=row[5],
                            similarity=0.0,
                        ))
    return results


_FAMILY_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s
  AND section = ANY(%s)
ORDER BY section, content
"""


def family_lookup(
    pool: ThreadedConnectionPool,
    sections: list[str],
    corpus_version: str,
) -> list[Chunk]:
    """Fetch every chunk of the given rule families (EXACT section labels,
    e.g. '809. Deflect' — the fine chunker splits one family across chunks).

    Like tagged_lookup this is a lexical match with no cosine: similarity
    stays 0.0 so completing a keyword's family never inflates confidence.
    ORDER BY content approximates rule order within a family (chunks start
    with '### <label>\\n<first rule code>').
    """
    if not sections:
        return []
    results: list[Chunk] = []
    with get_conn(pool) as conn:
        with conn.cursor() as cur:
            cur.execute(_FAMILY_SQL, (corpus_version, list(sections)))
            for row in cur.fetchall():
                results.append(Chunk(
                    id=str(row[0]),
                    content=row[1],
                    section=row[2],
                    parent_section=row[3],
                    source_type=row[4],
                    metadata=row[5],
                    similarity=0.0,
                ))
    return results
