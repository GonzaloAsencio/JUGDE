"""Semantic answer cache (improvement plan 2.3).

The exact cache (``app/cache.py``) keys on SHA-256 of the normalized question,
so every PARAPHRASE of an already-answered question is a miss that pays a full
LLM call. On a free tier that is what burns the quota. This module adds a second
lookup: on an exact miss, find the nearest previously-answered question by
cosine similarity and reuse its answer.

Split of responsibilities: Postgres stores ``embedding -> cache_key`` (pgvector
ANN, migration 007); the ANSWER itself stays in Redis under that key. A semantic
hit is therefore a pointer lookup followed by the normal Redis GET. The embedder
is local (bge-m3, zero cost), so a lookup costs one CPU embed + one ANN query —
never an LLM call.

Never-raise contract, exactly like ``app/cache.py``: any DB failure degrades to
a cache miss (None / no-op) with a warning. A cache is an optimization; it must
never be able to break a query.

SAFETY. The failure mode that matters here is a FALSE POSITIVE — serving the
answer to a DIFFERENT question. Three independent guards:

1. **Namespace isolation.** The ANN filters on corpus_version + prompt_version +
   directive_key, so a hit can never cross a corpus, prompt, or card-mention/@tag
   boundary — the same dimensions ``make_cache_key`` already hashes.
2. **A high cosine threshold** (``Settings.semantic_cache_threshold``), calibrated
   offline against the eval set by ``scripts/semantic_cache_probe.py``: it must
   sit above the highest similarity measured between two DIFFERENT eval
   questions, or false positives are guaranteed by construction.
3. **Freshness.** Rows older than the Redis TTL are excluded from the ANN — their
   answer has already expired, so they could only produce a pointer to nothing.
"""
from app.db import get_conn
from app.observability import get_logger

logger = get_logger(__name__)

# Nearest neighbour within the namespace. The threshold is applied in Python
# (not SQL) so the rejected near-miss can be logged — that log is what makes the
# "zero false positives, read by hand" gate auditable.
_LOOKUP_SQL = """
SELECT cache_key, question, 1 - (embedding <=> %s::vector) AS similarity
FROM cached_questions
WHERE corpus_version = %s
  AND prompt_version = %s
  AND directive_key = %s
  AND created_at > NOW() - MAKE_INTERVAL(secs => %s)
ORDER BY embedding <=> %s::vector
LIMIT 1;
"""

# ON CONFLICT: cache_key is a hash of (question, corpus, prompt, mentions), so a
# re-answered question is the SAME row — same question text, same embedding.
# The conflict must refresh created_at, not ignore: lookup's freshness filter
# excludes rows older than the Redis TTL, and DO NOTHING would leave the
# original timestamp in place forever. A question re-answered after expiry
# would then be regenerated and re-cached in Redis on every miss while its
# semantic pointer stayed permanently invisible — every entry dead 24h after
# its FIRST answer, which is the opposite of a cache.
_REMEMBER_SQL = """
INSERT INTO cached_questions
  (question, embedding, cache_key, corpus_version, prompt_version, directive_key)
VALUES (%s, %s::vector, %s, %s, %s, %s)
ON CONFLICT (cache_key) DO UPDATE SET created_at = NOW();
"""

_FORGET_SQL = "DELETE FROM cached_questions WHERE cache_key = %s;"


def lookup(
    pool,
    embedding: list[float],
    *,
    corpus_version: str,
    prompt_version: str,
    directive_key: str,
    threshold: float,
    ttl_s: int,
) -> tuple[str, str, float] | None:
    """Nearest answered question above *threshold*, or None.

    Returns ``(cache_key, question, similarity)`` — the matched question and its
    score come back so the caller can LOG the hit. Without them a false positive
    would be invisible in production.
    """
    try:
        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _LOOKUP_SQL,
                    (embedding, corpus_version, prompt_version, directive_key, ttl_s, embedding),
                )
                row = cur.fetchone()
    except Exception as e:
        logger.warning("semantic_cache.lookup_failed", error=str(e))
        return None

    if row is None:
        return None
    cache_key, question, similarity = row[0], row[1], float(row[2])
    if similarity < threshold:
        # The flip gate is "zero false positives, read by hand" — the rejected
        # near-miss is the data that calibrates the threshold in prod. This log
        # is why the threshold is applied here instead of in the SQL.
        logger.info(
            "semantic_cache.near_miss",
            similarity=round(similarity, 4),
            threshold=threshold,
            matched_question=question,
        )
        return None
    return cache_key, question, similarity


def remember(
    pool,
    question: str,
    embedding: list[float],
    cache_key: str,
    *,
    corpus_version: str,
    prompt_version: str,
    directive_key: str,
) -> None:
    """Record that *question* was answered under *cache_key*. No-op on error.

    Only ever called for answers the caller already decided are cacheable — a
    degraded answer must never be remembered here, for the same reason it is
    never written to Redis (see ``pipeline.answer_question``).
    """
    try:
        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    _REMEMBER_SQL,
                    (question, embedding, cache_key, corpus_version, prompt_version, directive_key),
                )
            conn.commit()
    except Exception as e:
        logger.warning("semantic_cache.remember_failed", error=str(e))


def forget(pool, cache_key: str) -> None:
    """Drop a row whose Redis answer is gone. No-op on error.

    Self-healing: the freshness filter in *lookup* uses the row's age as a proxy
    for the Redis TTL, but Redis can evict early (memory pressure on the free
    tier). When a pointer resolves to nothing, delete it so it stops being
    returned as the nearest neighbour and shadowing a real hit.
    """
    try:
        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(_FORGET_SQL, (cache_key,))
            conn.commit()
    except Exception as e:
        logger.warning("semantic_cache.forget_failed", error=str(e))
