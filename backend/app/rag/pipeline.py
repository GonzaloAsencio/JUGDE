import json
import re
import time
import uuid
from dataclasses import dataclass

from app import semantic_cache
from app.cache import directive_key, get_cached, make_cache_key, set_cached
from app.cache import is_enabled as cache_is_enabled
from app.config import Settings
from app.observability import get_logger
from app.rag.embedder import Embedder
from app.rag.generation import (
    _MULTI_CARD_SCAFFOLD,
    _SAFE_FALLBACK,
    has_empty_answer_section,
    needs_scaffold,
    post_gen_validate,
    strip_citation_markers,
)
from app.rag.provider import LLMProvider
from app.rag.card_detect import detect_card_mentions, detect_champion_mentions, load_card_names
from app.rag.reranker import rerank
from app.rag.retrieval import family_lookup, fuse_results, hybrid_search, tagged_lookup
from app.rag.routing import RULEBOOK_CHUNK_ID, build_stuffed_chunks, is_hard_query, load_champion_tag_index
from app.rag.rules import extract_rule_codes
from app.rag.schemas import Citation, QueryResponse

logger = get_logger(__name__)

_NO_INFO_ANSWER = "I don't have enough information to answer that question with the available rules."
_INCONCLUSIVE_ANSWER = (
    "I couldn't reach a definitive answer for this question from the available rules — "
    "the situation appears ambiguous or not fully resolved by the current rulebook."
)
_TAG_RE = re.compile(r"@(\w+)", re.UNICODE)

# Answers produced by failure paths, not by the model answering the question:
# safety block / prompt-leak sanitization (_SAFE_FALLBACK), empty-Answer retry
# exhausted (_INCONCLUSIVE_ANSWER), or no-info. These are usually transient, so
# they must never be frozen in the cache (see answer_question).
_DEGRADED_ANSWERS: frozenset[str] = frozenset({
    _NO_INFO_ANSWER,
    _INCONCLUSIVE_ANSWER,
    _SAFE_FALLBACK,
})

_KNOWN_KEYWORDS: frozenset[str] = frozenset({
    # Card keywords (rules text on cards)
    "accelerate", "action", "assault", "deathknell", "deflect",
    "ganking", "hidden", "legion", "reaction", "shield", "tank",
    "temporary", "vision", "equip", "quick-draw", "repeat",
    "weaponmaster", "ambush", "hunt", "level", "unique", "backline",
    # Game actions (dedicated rulebook sections 413-431)
    "stun", "draw", "exhaust", "ready", "recycle", "channel",
    "kill", "buff", "banish", "counter", "burn out", "recall",
    "discard", "reveal",
    # Core game concepts (dedicated rulebook sections)
    "chain", "showdown", "priority", "cleanup", "combat",
    "scoring", "token", "replacement",
    # Additional concepts with dedicated sections
    "main phase", "mighty",
})

# Community terms → official rulebook section names
_KEYWORD_ALIASES: dict[str, str] = {
    "action phase": "main phase",
}

# Sección de regla numerada ('820. Repeat') — distingue el chunk de la REGLA de
# un keyword de las cartas que matchean el tag por ILIKE ('Hunters Machete').
_RULE_SECTION = re.compile(r"^\d{3,}\. ")


def _word_boundary(term: str) -> "re.Pattern[str]":
    """Compile a case-insensitive whole-word matcher for *term*."""
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


# Precompiled whole-word matchers. A substring match wrongly fired on common
# English words embedded in other words ('ready' inside 'already', 'equip'
# inside 'equipment'), tagging — and then evicting — the real semantic chunks.
_KEYWORD_PATTERNS: dict[str, "re.Pattern[str]"] = {kw: _word_boundary(kw) for kw in _KNOWN_KEYWORDS}
_ALIAS_PATTERNS: dict[str, "re.Pattern[str]"] = {alias: _word_boundary(alias) for alias in _KEYWORD_ALIASES}


def _detect_keywords(question: str) -> list[str]:
    """Return known keywords found in question via case-insensitive whole-word match.

    Whole-word (not substring) so 'already' does not match 'ready' and
    'equipment' does not match 'equip'. Also resolves community aliases to their
    official rulebook section names.
    """
    found = [kw for kw in _KNOWN_KEYWORDS if _KEYWORD_PATTERNS[kw].search(question)]
    for alias, canonical in _KEYWORD_ALIASES.items():
        if _ALIAS_PATTERNS[alias].search(question) and canonical not in found:
            found.append(canonical)
    return found


def _has_exact_card_match(chunks: list, card_match_tags: set[str]) -> bool:
    """True if any card tag appears as a WHOLE WORD in a surviving chunk's section.

    Whole-word (not substring): a substring test let tag "jhin" match section
    "Jhinx" and wrongly force confidence to 1.0. Consistent with the whole-word
    matching used everywhere else in this module (see _word_boundary).
    """
    if not card_match_tags:
        return False
    patterns = [_word_boundary(tag) for tag in card_match_tags]
    return any(p.search(chunk.section) for chunk in chunks for p in patterns)


def _extract_tags(question: str) -> tuple[str, list[str]]:
    """Extract @tags from question. Returns (clean_question, [tags_lowercase])."""
    tags = _TAG_RE.findall(question)
    clean = _TAG_RE.sub("", question).strip()
    return clean, [t.lower() for t in tags]


def _assemble_context(
    explicit_chunks: list, semantic_chunks: list, auto_chunks: list, top_k: int
) -> list:
    """Merge the three context sources into a top_k budget, deduped by id.

    Priority of the limited budget:
      1. Explicit chunks (from @tags / card_mentions) prepend — a user-directed
         lookup — but cannot consume the whole budget: at least one slot is
         reserved for semantic retrieval when any is available.
      2. Semantic chunks (real cosine) fill next — minus one slot when a
         keyword RULE chunk (numbered section like '820. Repeat') is waiting:
         a detected keyword's own rule is exactly what the question needs, and
         leftover-only budgeting never let it in (diagnosed on eval-037). The
         slot is backfilled by semantic if the rule chunk arrives as a dup.
      3. Other auto-detected keyword chunks fill ONLY leftover budget. They are
         a lexical heuristic (similarity=0.0) and must never displace a real
         semantic hit — the bug that evicted card chunks from rulings.

    Never returns more than top_k chunks.
    """
    seen: set[str] = set()
    result: list = []

    def take(chunks: list, limit: int) -> None:
        for c in chunks:
            if len(result) >= limit:
                break
            if c.id not in seen:
                seen.add(c.id)
                result.append(c)

    semantic_available = any(c.id not in seen for c in semantic_chunks)
    explicit_limit = top_k - 1 if semantic_available and top_k > 1 else top_k
    take(explicit_chunks, explicit_limit)

    rule_autos = [c for c in auto_chunks if _RULE_SECTION.match(c.section or "")]
    semantic_limit = top_k - 1 if rule_autos and top_k > 1 else top_k
    take(semantic_chunks, semantic_limit)
    take(rule_autos, top_k)
    take(semantic_chunks, top_k)  # backfill the reserved slot if the rule chunk was a dup
    take(auto_chunks, top_k)
    return result


def _complete_keyword_families(context: list, family_chunks: list, extra_cap: int) -> list:
    """Append the missing siblings of keyword rule families AFTER the top_k
    context (3.5 small-to-big at rule-family granularity).

    The fine chunker deliberately splits a rule family ('809. Deflect') across
    chunks so each embeds sharply — but the keyword reserved slot then admits
    only the first chunk, and the rule the question needs may live in a sibling
    (eval-030: 809.1 was in a dropped chunk). Completion re-unites the family
    for the LLM without touching what retrieval chose: siblings only ever
    APPEND beyond top_k, capped at *extra_cap*, so no semantic hit is ever
    evicted (the eviction mechanism that killed query decomposition in 3.2).
    """
    if extra_cap <= 0 or not family_chunks:
        return context
    seen = {c.id for c in context}
    tail = []
    for c in family_chunks:
        if len(tail) >= extra_cap:
            break
        if c.id not in seen:
            seen.add(c.id)
            tail.append(c)
    return list(context) + tail


def _try_cached_response(cache_key: str, settings: Settings, query_id: str, t0: float) -> QueryResponse | None:
    """Return a cached QueryResponse for *cache_key*, or None on miss/corruption.

    Runs after Pydantic validation + rate limit (see ADR-1). A corrupt cache
    entry returns None so the caller falls through to fresh generation.
    """
    cached_raw = get_cached(cache_key)
    if cached_raw is None:
        return None
    try:
        cached_data = json.loads(cached_raw)
        latency_ms = round((time.time() - t0) * 1000)
        response = QueryResponse(**{**cached_data, "cache_hit": True, "latency_ms": latency_ms})
    except Exception:
        return None  # Corrupt cache entry — fall through to generation
    logger.info(
        "query.complete",
        query_id=query_id,
        latency_ms=latency_ms,
        cache_hit=True,
        model=settings.llm_model or settings.gemini_model,
        confidence=response.confidence,
    )
    return response


@dataclass(frozen=True)
class _Entities:
    """Deterministic entity signal for a question — no LLM, no cosine.

    Shared by the semantic-cache gate (which must classify a query BEFORE paying
    for retrieval) and _retrieve (which needs the same tags to build context).
    Computed once per query and threaded through so the ~960-pattern card scan
    doesn't run twice.
    """
    auto_card_tags: list[str]
    ambiguous_champion_count: int

    def card_count(self, mention_tags: list[str]) -> int:
        return len(set(self.auto_card_tags) | set(mention_tags)) + self.ambiguous_champion_count


def _detect_entities(
    base_question: str, db_pool, corpus_version: str, query_id: str
) -> _Entities:
    """Auto-detect card names + bare champion mentions in the question.

    Multi-card interaction questions embed poorly (the scenario prose dominates
    the cosine), so named cards rarely surface in semantic retrieval — a
    deterministic probe found 9/12 named cards ABSENT from context on the hard
    bucket. Detected names join the user-directed tags so tagged_lookup pulls
    them into reserved slots (see _assemble_context).

    Best-effort: a vocabulary-load failure must never break query answering, so
    the feature degrades to the prior behaviour instead of raising.
    """
    auto_card_tags: list[str] = []
    ambiguous_champion_count = 0
    try:
        card_vocab = load_card_names(db_pool, corpus_version)
        auto_card_tags = [
            c.lower()
            for c in detect_card_mentions(base_question, card_vocab, known_keywords=_KNOWN_KEYWORDS)
        ]
        # Bare champion mentions ("a Vi") the vocabulary above can't see (it
        # only holds full printed names). Unambiguous tags resolve to their
        # one card and join auto_card_tags like any other exact match;
        # ambiguous ones (e.g. "Vi" has 7 printed variants) resolve to
        # nothing here but still count as a distinct entity — see
        # card_detect.detect_champion_mentions for why we never guess.
        resolved_champions, ambiguous_champion_count = detect_champion_mentions(
            base_question, load_champion_tag_index(), known_keywords=_KNOWN_KEYWORDS
        )
        auto_card_tags += [c.lower() for c in resolved_champions if c.lower() not in auto_card_tags]
    except Exception as e:  # pragma: no cover - defensive: never fail a query on detection
        logger.warning("card_detect.failed", query_id=query_id, error=str(e))
    return _Entities(auto_card_tags=auto_card_tags, ambiguous_champion_count=ambiguous_champion_count)


def _semantic_cache_is_safe(*, card_count: int, keyword_count: int) -> bool:
    """Whether a question may be answered from the SEMANTIC cache (2.3).

    Hard (multi-entity) questions must NEVER be, and this is measured, not
    cautious. scripts/semantic_cache_probe.py found an adversarial pair inside
    our own eval set:

        eval-013: "... I play Tideturner DURING MY OPPONENT'S TURN ..." -> YES
        eval-014: "... I play Tideturner ON MY OWN TURN ..."            -> NO

    Cosine similarity: 0.982. Two words apart, OPPOSITE rulings — because
    383.3.d.1 hangs the whole answer on who the turn player is. Across the full
    eval set the highest different-question cosine is that 0.982, while the
    LOWEST self-paraphrase cosine is 0.874: there is no threshold that both
    rejects the wrong answer and still catches a reworded question. Globally,
    this feature cannot be made safe at any threshold.

    Restricted to NON-hard questions the picture inverts: the ceiling drops to
    0.763 against the same 0.874 floor, leaving a wide safe band. That is not a
    coincidence — rules questions hinge on discriminative micro-details (whose
    turn, which zone, ready vs exhausted) that embeddings smooth over, and those
    details are exactly what makes a question hard in the first place.

    So the gate reuses is_hard_query: the same classifier that routes a question
    to the thinking model also disqualifies it from the semantic cache.
    """
    return not is_hard_query(card_count=card_count, keyword_count=keyword_count)


def _try_semantic_response(
    db_pool,
    question_embedding: list[float],
    semantic_key: str,
    corpus_version: str,
    cache_prompt_version: str,
    settings: Settings,
    query_id: str,
    t0: float,
) -> QueryResponse | None:
    """Return the answer of the nearest already-answered question, or None (2.3).

    Runs only after the exact key missed. The neighbour's answer lives in Redis;
    this resolves the pointer and reuses it.

    Every hit is logged with the matched question and its cosine — the gate for
    turning this feature on is "zero false positives, read by hand", and a hit
    that isn't visible cannot be audited.
    """
    match = semantic_cache.lookup(
        db_pool, question_embedding,
        corpus_version=corpus_version,
        prompt_version=cache_prompt_version,
        directive_key=semantic_key,
        threshold=settings.semantic_cache_threshold,
        ttl_s=settings.cache_ttl_s,
    )
    if match is None:
        return None
    neighbour_key, neighbour_question, similarity = match

    cached_raw = get_cached(neighbour_key)
    if cached_raw is None:
        # The pointer outlived its answer (early Redis eviction). Drop the row so
        # it stops shadowing a real neighbour, and fall through to generation.
        logger.info("semantic_cache.stale_pointer", query_id=query_id, similarity=similarity)
        semantic_cache.forget(db_pool, neighbour_key)
        return None
    try:
        cached_data = json.loads(cached_raw)
        latency_ms = round((time.time() - t0) * 1000)
        response = QueryResponse(**{**cached_data, "cache_hit": True, "latency_ms": latency_ms})
    except Exception:
        return None  # Corrupt entry — regenerate rather than serve garbage.

    logger.info(
        "semantic_cache.hit",
        query_id=query_id,
        similarity=round(similarity, 4),
        matched_question=neighbour_question,
        latency_ms=latency_ms,
    )
    return response


def _retrieve(
    question: str,
    embedder: Embedder,
    db_pool,
    provider: LLMProvider,
    settings: Settings,
    card_mentions: list[str] | None,
    corpus_version: str,
    query_id: str,
    question_embedding: list[float] | None = None,
    entities: "_Entities | None" = None,
) -> tuple[list, str, float, bool, int]:
    """Embed + retrieve + assemble the final context.

    Returns (chunks, clean_question, semantic_confidence, has_exact_card_match, card_count).

    *question_embedding* and *entities* let the caller hand in work it already
    did. The semantic cache (2.3) must classify the query and embed it BEFORE
    this call — recomputing either here would pay bge-m3's CPU cost (~50-100ms)
    and the ~960-pattern card scan twice for the identical text. None -> compute
    here, as before.
    """
    clean_question, explicit_tags = _extract_tags(question)
    base_question = clean_question or question
    auto_tags = _detect_keywords(base_question)
    mention_tags = [m.lower() for m in (card_mentions or [])]

    if entities is None:
        entities = _detect_entities(base_question, db_pool, corpus_version, query_id)
    auto_card_tags = entities.auto_card_tags
    ambiguous_champion_count = entities.ambiguous_champion_count

    # User-directed tags (@tags + card mentions + auto-detected cards) may prepend;
    # auto-detected KEYWORDS are a weaker heuristic and only fill leftover budget.
    directed_tags = list(dict.fromkeys(explicit_tags + mention_tags + auto_card_tags))
    auto_only_tags = [t for t in auto_tags if t not in directed_tags]

    explicit_chunks = tagged_lookup(db_pool, directed_tags, corpus_version) if directed_tags else []
    auto_chunks = tagged_lookup(db_pool, auto_only_tags, corpus_version) if auto_only_tags else []

    # Retrieval: fuse_eq strategy (offline experiment winner, recall@5 41%->59%).
    # Arm A embeds the RAW question; arm B embeds a HyDE passage when the provider
    # supplies one, and the two hybrid_search lists are RRF-fused. Without a HyDE
    # passage we run arm A alone, so providers that don't implement HyDE keep
    # their current raw-only behaviour. The earlier rewrite_query path is dropped
    # here on purpose: the experiment never measured it (pending: test as a 4th arm).
    #
    # When fusing, each arm fetches at top_k_fetch depth and fuse_results truncates
    # ONCE to pool_k. Truncating each arm to top_k first (double truncation) dropped
    # a chunk strong in only one arm — e.g. a card at raw rank 3 lost to the HyDE
    # arm before fusion even ran. HyDE is resolved first so we know the arm depth.
    #
    # pool_k (D2): the reranker only helps if it sees MORE candidates than it
    # returns. When enable_reranker is off, pool_k == top_k — byte-identical to
    # pre-reranker behaviour (the regression guarantee). When on, the pool is
    # widened to rerank_pool_size and reranked back down to top_k below.
    pool_k = settings.rerank_pool_size if settings.enable_reranker else settings.top_k
    hyde_text = provider.hyde(base_question)
    arm_top_k = settings.top_k_fetch if hyde_text else pool_k
    base_embedding = (
        question_embedding if question_embedding is not None else embedder.encode(base_question)
    )
    chunks = hybrid_search(
        db_pool, base_embedding, base_question, corpus_version,
        top_k=arm_top_k,
        top_k_fetch=settings.top_k_fetch,
        rrf_k=settings.rrf_k,
    )
    if hyde_text:
        hyde_chunks = hybrid_search(
            db_pool, embedder.encode(hyde_text), hyde_text, corpus_version,
            top_k=arm_top_k,
            top_k_fetch=settings.top_k_fetch,
            rrf_k=settings.rrf_k,
        )
        chunks = fuse_results(chunks, hyde_chunks, rrf_k=settings.rrf_k, top_k=pool_k)

    # Rerank the semantic pool ONLY — never the tagged/explicit chunks below.
    # tagged_lookup is a deterministic entity match that drives
    # has_exact_card_match -> confidence 1.0 with reserved slots in
    # _assemble_context; letting the cross-encoder reorder or evict that chunk
    # would silently degrade the strongest signal we have. Never-raise: rerank()
    # already wraps model load/predict failures internally, but a defense-in-depth
    # try/except here means a query never breaks even if rerank() itself is
    # mocked/misbehaves in an unexpected way.
    if settings.enable_reranker:
        try:
            chunks = rerank(base_question, chunks, top_k=settings.top_k, model_name=settings.reranker_model)
        except Exception as e:  # pragma: no cover - defensive, rerank() itself never raises
            logger.warning("reranker.pipeline_fallback", query_id=query_id, error=str(e))
            chunks = chunks[: settings.top_k]

    # Confidence reflects the strength of REAL semantic retrieval: the best cosine
    # similarity among the vector-search results. Captured BEFORE tagged chunks are
    # prepended, because tagged_lookup is a lexical match with no cosine — letting
    # it set confidence would report 1.0 for any query that merely matches a tag.
    semantic_confidence = max((c.similarity for c in chunks), default=0.0)

    chunks = _assemble_context(explicit_chunks, chunks, auto_chunks, settings.top_k)

    # 3.5 keyword family completion (flag off by default): when a detected
    # keyword's rule chunk made it into context, fetch its complete family and
    # append the missing siblings beyond top_k. Only families whose slot chunk
    # actually survived assembly are completed — a keyword whose rule never
    # entered the context gets no free ride.
    if settings.keyword_family_extra > 0:
        kw_sections = {c.section for c in auto_chunks if _RULE_SECTION.match(c.section or "")}
        fam_sections = sorted(kw_sections & {c.section for c in chunks})
        if fam_sections:
            family = family_lookup(db_pool, fam_sections, corpus_version)
            chunks = _complete_keyword_families(chunks, family, settings.keyword_family_extra)

    # Exact card detection (auto-detected names + user @mentions) is the most
    # precise retrieval we have — a deterministic entity match, not a fuzzy cosine.
    # tagged_lookup keeps per-chunk similarity at 0.0 on purpose (see retrieval.py),
    # so the semantic-cosine confidence would UNDERSTATE these. When a detected
    # card survived into the final context, treat confidence as maximal. This is
    # scoped to cards only — generic @tags/keywords still must not inflate.
    card_match_tags = set(auto_card_tags) | set(mention_tags)
    has_exact_card_match = _has_exact_card_match(chunks, card_match_tags)

    # card_count feeds needs_scaffold (PR3, hard-bucket-v2): the multi-card
    # reasoning scaffold triggers on 2+ distinct cards regardless of whether
    # they survived into the final context (an under-retrieved card is still
    # a multi-card question that needs the enumerate/resolve/conclude guidance).
    # ambiguous_champion_count adds bare champion mentions that couldn't
    # resolve to one printed card ("a Vi") — still a distinct entity for
    # routing purposes even though no specific card text was attached.
    card_count = len(card_match_tags) + ambiguous_champion_count

    return chunks, clean_question, semantic_confidence, has_exact_card_match, card_count


def _build_citations(chunks: list) -> list[Citation]:
    """Build the citation list from the final context chunks."""
    return [
        Citation(
            section=chunk.section,
            source_type=chunk.source_type,
            content_preview=chunk.content[:200],
            similarity=chunk.similarity,
            chunk_id=chunk.id,
            set=(chunk.metadata or {}).get("set"),
            # The stuffed rulebook chunk is the WHOLE rulebook: deriving
            # rule_codes from it would list every code in the game (response
            # bloat, and a guaranteed paper hit for the eval recall matcher).
            rule_codes=[] if chunk.id == RULEBOOK_CHUNK_ID
            else sorted(extract_rule_codes(chunk.content)),
        )
        for chunk in chunks
    ]


def _postprocess_answer(answer: str, citations: list, chunks: list, query_id: str) -> str:
    """Validate + clean the generated answer. May mutate/clear *citations* in place."""
    valid_ids = {chunk.id for chunk in chunks}
    answer, _ = post_gen_validate(answer, citations, valid_chunk_ids=valid_ids)

    # Drop the [#N] citation scaffolding — the frontend renders sources from the
    # citations list, so the inline markers are redundant noise in the text.
    answer = strip_citation_markers(answer)

    # Strip trailing no-info disclaimer when the model appended it to a real answer.
    _no_info_variants = [
        f"Therefore, {_NO_INFO_ANSWER}",
        _NO_INFO_ANSWER,
    ]
    for _variant in _no_info_variants:
        if answer.endswith(_variant) and len(answer) > len(_variant):
            answer = answer[: -len(_variant)].rstrip(" \n.,;")
            break

    if answer == _NO_INFO_ANSWER and chunks:
        logger.warning(
            "query.no_info_despite_context",
            query_id=query_id,
            top_sim=round(chunks[0].similarity, 4),
            chunk_count=len(chunks),
        )
        citations.clear()

    return answer


def _compute_confidence(semantic_confidence: float, has_exact_card_match: bool, citations: list) -> float:
    """Confidence for the response: 0.0 without citations, 1.0 on an exact card
    match, else the rounded best semantic cosine."""
    if not citations:
        return 0.0
    if has_exact_card_match:
        return 1.0
    return round(semantic_confidence, 4)


def _generate_guarded(
    provider: LLMProvider, question: str, chunks: list, query_id: str, *, extra_system: str = ""
) -> str:
    """Generate an answer, retrying ONCE if the Answer section comes back empty.

    Gemini occasionally writes a full Reasoning block on an ambiguous question
    and then stops without a conclusion (see has_empty_answer_section). The
    failure is non-deterministic, so a single fresh call — with no carried-over
    reasoning to trail off from — recovers the vast majority. If the retry is
    also empty we return a controlled inconclusive message so the user never
    sees a blank answer bubble.

    *extra_system* (PR3, hard-bucket-v2) carries the multi-card reasoning
    scaffold decided by the caller and is forwarded unchanged on every attempt.
    """
    answer = provider.generate(question, chunks, extra_system=extra_system)
    if not has_empty_answer_section(answer):
        return answer

    logger.warning("query.empty_answer_section", query_id=query_id, attempt=1)
    answer = provider.generate(question, chunks, extra_system=extra_system)
    if not has_empty_answer_section(answer):
        return answer

    logger.warning("query.empty_answer_after_retry", query_id=query_id)
    return _INCONCLUSIVE_ANSWER


def answer_question(
    question: str,
    embedder: Embedder,
    db_pool,
    provider: LLMProvider,
    settings: Settings,
    card_mentions: list[str] | None = None,
    corpus_version: str | None = None,
    hard_provider: LLMProvider | None = None,
) -> QueryResponse:
    """Orchestrate embed -> retrieve -> generate with cache, tracing, and post-gen validation.

    Synchronous by design: every collaborator (embedder, psycopg2, LLM clients,
    Upstash cache) is blocking. The endpoint is a sync handler, so FastAPI runs
    this in its threadpool — real concurrency without an ``async`` facade that
    would only block the event loop.
    """
    t0 = time.time()
    query_id = str(uuid.uuid4())

    # Resolved corpus_version is passed in explicitly (from app.state) by the
    # endpoint. Falling back to settings keeps existing callers/tests working
    # without mutating the cached Settings singleton (see main.py).
    corpus_version = corpus_version or settings.corpus_version or "latest"
    # Routed answers come from a different model AND context, but the routing
    # decision needs retrieval (card_count) and thus happens after the cache
    # lookup — so the ROUTED bit can't be in the key. Keying the namespace on
    # the FLAG instead keeps the cache coherent across the two-step flip: a
    # flip (either direction) starts cold rather than serving up to
    # cache_ttl_s of answers produced by the other mode. Flag off ->
    # byte-identical key to pre-routing behaviour.
    cache_prompt_version = (
        settings.prompt_version + "+hard-routing"
        if settings.hard_query_routing else settings.prompt_version
    )
    cache_key = make_cache_key(question, corpus_version, card_mentions, cache_prompt_version)

    cached = _try_cached_response(cache_key, settings, query_id, t0)
    if cached is not None:
        return cached

    # 2.3 semantic cache (flag off by default). The exact key above is a hash, so
    # a paraphrase of an already-answered question misses it and pays a full LLM
    # call. Classify FIRST (deterministic, no LLM), because the cache is only
    # safe for one half of the traffic — see _semantic_cache_is_safe.
    tag_stripped, explicit_tags = _extract_tags(question)
    base_question = tag_stripped or question
    mention_tags = [m.lower() for m in (card_mentions or [])]
    semantic_key = directive_key(card_mentions, explicit_tags)

    entities: _Entities | None = None
    question_embedding: list[float] | None = None
    semantic_eligible = False
    if settings.semantic_cache_enabled and cache_is_enabled():
        entities = _detect_entities(base_question, db_pool, corpus_version, query_id)
        semantic_eligible = _semantic_cache_is_safe(
            card_count=entities.card_count(mention_tags),
            keyword_count=len(_detect_keywords(base_question)),
        )
        if semantic_eligible:
            question_embedding = embedder.encode(base_question)
            semantic = _try_semantic_response(
                db_pool, question_embedding, semantic_key, corpus_version,
                cache_prompt_version, settings, query_id, t0,
            )
            if semantic is not None:
                return semantic

    chunks, clean_question, semantic_confidence, has_exact_card_match, card_count = _retrieve(
        question, embedder, db_pool, provider, settings, card_mentions, corpus_version, query_id,
        question_embedding=question_embedding, entities=entities,
    )

    resolved_question = clean_question or question

    # 4.2+4.3 hard-query routing (flag off by default): multi-entity questions
    # fail on reasoning, not retrieval — probes showed their gold rules are out
    # of reach of every retrieval expansion, but a thinking model over the FULL
    # rulebook answers them. Hard queries swap the retrieved context for the
    # stuffed one and generate on the hard provider; the retrieval above still
    # ran and keeps supplying the confidence signals (semantic cosine + exact
    # card match), whose meaning doesn't change with the routed context.
    # hard_provider is None whenever the flag is off (see main.py), so the
    # normal path stays byte-identical.
    routed = False
    if hard_provider is not None and settings.hard_query_routing and is_hard_query(
        card_count=card_count, keyword_count=len(_detect_keywords(resolved_question))
    ):
        stuffed = build_stuffed_chunks(
            resolved_question,
            known_keywords=_KNOWN_KEYWORDS,
            extra_card_names=tuple(card_mentions or ()),
        )
        if stuffed is not None:
            chunks = stuffed
            routed = True
            logger.info(
                "query.routed_hard",
                query_id=query_id,
                card_count=card_count,
                stuffed_chunks=len(stuffed),
            )

    model = settings.hard_gemini_model if routed else (settings.llm_model or settings.gemini_model)

    if not chunks:
        latency_ms = round((time.time() - t0) * 1000)
        logger.info(
            "query.complete",
            query_id=query_id,
            latency_ms=latency_ms,
            cache_hit=False,
            model=model,
            confidence=0.0,
        )
        return QueryResponse(
            answer=_NO_INFO_ANSWER,
            citations=[],
            latency_ms=latency_ms,
            cache_hit=False,
            confidence=0.0,
        )

    extra_system = _MULTI_CARD_SCAFFOLD if needs_scaffold(resolved_question, card_count) else ""
    answer = _generate_guarded(
        hard_provider if routed else provider,
        resolved_question, chunks, query_id, extra_system=extra_system,
    )
    citations = _build_citations(chunks)
    answer = _postprocess_answer(answer, citations, chunks, query_id)

    latency_ms = round((time.time() - t0) * 1000)
    confidence = _compute_confidence(semantic_confidence, has_exact_card_match, citations)

    response = QueryResponse(
        answer=answer,
        citations=citations,
        latency_ms=latency_ms,
        cache_hit=False,
        confidence=confidence,
    )

    # Store in cache (non-blocking; errors are swallowed in set_cached) — but
    # NEVER cache a degraded response. A transient failure (safety block,
    # empty-Answer retry exhausted, no-info despite context — the latter always
    # ends with confidence 0.0 because citations are cleared) would otherwise be
    # frozen for cache_ttl_s and served to every user asking the same question.
    # The next request simply regenerates; rate limiting bounds the retry cost.
    if confidence == 0.0 or answer in _DEGRADED_ANSWERS:
        logger.info("cache.skip_degraded", query_id=query_id, confidence=confidence)
    else:
        set_cached(
            cache_key,
            json.dumps({"answer": answer, "citations": [c.model_dump() for c in citations], "confidence": confidence}),
            ttl=settings.cache_ttl_s,
        )
        # Index the question for the semantic cache under the SAME key. Gated on
        # the same degraded check on purpose: a pointer to an answer Redis was
        # told not to store would only ever resolve to nothing. Gated on
        # semantic_eligible too — a hard question must not even be REMEMBERED,
        # or it becomes the wrong-answer neighbour for the next paraphrase
        # (see _semantic_cache_is_safe).
        if semantic_eligible and question_embedding is not None:
            semantic_cache.remember(
                db_pool,
                base_question,
                question_embedding,
                cache_key,
                corpus_version=corpus_version,
                prompt_version=cache_prompt_version,
                directive_key=semantic_key,
            )

    logger.info(
        "query.complete",
        query_id=query_id,
        latency_ms=latency_ms,
        cache_hit=False,
        model=model,
        confidence=confidence,
    )

    return response
