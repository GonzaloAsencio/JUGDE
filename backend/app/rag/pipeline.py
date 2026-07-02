import json
import re
import time
import uuid

from app.cache import get_cached, make_cache_key, set_cached
from app.config import Settings
from app.observability import get_logger
from app.rag.embedder import Embedder
from app.rag.generation import post_gen_validate, strip_citation_markers
from app.rag.provider import LLMProvider
from app.rag.card_detect import detect_card_mentions, load_card_names
from app.rag.retrieval import fuse_results, hybrid_search, tagged_lookup
from app.rag.rules import extract_rule_codes
from app.rag.schemas import Citation, QueryResponse

logger = get_logger(__name__)

_NO_INFO_ANSWER = "I don't have enough information to answer that question with the available rules."
_TAG_RE = re.compile(r"@(\w+)", re.UNICODE)

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
      2. Semantic chunks (real cosine) fill next.
      3. Auto-detected keyword chunks fill ONLY leftover budget. They are a
         lexical heuristic (similarity=0.0) and must never displace a real
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
    take(semantic_chunks, top_k)
    take(auto_chunks, top_k)
    return result


def answer_question(
    question: str,
    embedder: Embedder,
    db_pool,
    provider: LLMProvider,
    settings: Settings,
    card_mentions: list[str] | None = None,
) -> QueryResponse:
    """Orchestrate embed -> retrieve -> generate with cache, tracing, and post-gen validation.

    Synchronous by design: every collaborator (embedder, psycopg2, LLM clients,
    Upstash cache) is blocking. The endpoint is a sync handler, so FastAPI runs
    this in its threadpool — real concurrency without an ``async`` facade that
    would only block the event loop.
    """
    t0 = time.time()
    query_id = str(uuid.uuid4())

    corpus_version = settings.corpus_version or "latest"
    cache_key = make_cache_key(question, corpus_version, card_mentions, settings.prompt_version)

    # Cache check — runs after Pydantic validation + rate limit (see ADR-1)
    cached_raw = get_cached(cache_key)
    if cached_raw is not None:
        try:
            cached_data = json.loads(cached_raw)
            latency_ms = round((time.time() - t0) * 1000)
            cached_response = QueryResponse(**{**cached_data, "cache_hit": True, "latency_ms": latency_ms})
            logger.info(
                "query.complete",
                query_id=query_id,
                latency_ms=latency_ms,
                cache_hit=True,
                model=settings.llm_model or settings.gemini_model,
                confidence=cached_response.confidence,
            )
            return cached_response
        except Exception:
            pass  # Corrupt cache entry — fall through to generation

    clean_question, explicit_tags = _extract_tags(question)
    base_question = clean_question or question
    auto_tags = _detect_keywords(base_question)
    mention_tags = [m.lower() for m in (card_mentions or [])]

    # Auto-detect card names in the question. Multi-card interaction questions
    # embed poorly (the scenario prose dominates the cosine), so named cards rarely
    # surface in semantic retrieval — a deterministic probe found 9/12 named cards
    # ABSENT from context on the hard bucket. Detected names join the user-directed
    # tags so tagged_lookup pulls them into reserved slots (see _assemble_context).
    # Best-effort: a vocabulary-load failure must never break query answering, so
    # the feature degrades to the prior behaviour instead of raising.
    auto_card_tags: list[str] = []
    try:
        card_vocab = load_card_names(db_pool, corpus_version)
        auto_card_tags = [
            c.lower()
            for c in detect_card_mentions(base_question, card_vocab, known_keywords=_KNOWN_KEYWORDS)
        ]
    except Exception as e:  # pragma: no cover - defensive: never fail a query on detection
        logger.warning("card_detect.failed", query_id=query_id, error=str(e))

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
    # ONCE to top_k. Truncating each arm to top_k first (double truncation) dropped
    # a chunk strong in only one arm — e.g. a card at raw rank 3 lost to the HyDE
    # arm before fusion even ran. HyDE is resolved first so we know the arm depth.
    hyde_text = provider.hyde(base_question)
    arm_top_k = settings.top_k_fetch if hyde_text else settings.top_k
    chunks = hybrid_search(
        db_pool, embedder.encode(base_question), base_question, corpus_version,
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
        chunks = fuse_results(chunks, hyde_chunks, rrf_k=settings.rrf_k, top_k=settings.top_k)

    # Confidence reflects the strength of REAL semantic retrieval: the best cosine
    # similarity among the vector-search results. Captured BEFORE tagged chunks are
    # prepended, because tagged_lookup is a lexical match with no cosine — letting
    # it set confidence would report 1.0 for any query that merely matches a tag.
    semantic_confidence = max((c.similarity for c in chunks), default=0.0)

    chunks = _assemble_context(explicit_chunks, chunks, auto_chunks, settings.top_k)

    # Exact card detection (auto-detected names + user @mentions) is the most
    # precise retrieval we have — a deterministic entity match, not a fuzzy cosine.
    # tagged_lookup keeps per-chunk similarity at 0.0 on purpose (see retrieval.py),
    # so the semantic-cosine confidence would UNDERSTATE these. When a detected
    # card survived into the final context, treat confidence as maximal. This is
    # scoped to cards only — generic @tags/keywords still must not inflate.
    card_match_tags = set(auto_card_tags) | set(mention_tags)
    has_exact_card_match = _has_exact_card_match(chunks, card_match_tags)

    retrieval_ms = round((time.time() - t0) * 1000)

    if not chunks:
        latency_ms = retrieval_ms
        logger.info(
            "query.complete",
            query_id=query_id,
            latency_ms=latency_ms,
            cache_hit=False,
            model=settings.llm_model or settings.gemini_model,
            confidence=0.0,
        )
        return QueryResponse(
            answer=_NO_INFO_ANSWER,
            citations=[],
            latency_ms=latency_ms,
            cache_hit=False,
            confidence=0.0,
        )

    answer = provider.generate(clean_question or question, chunks)

    citations = [
        Citation(
            section=chunk.section,
            source_type=chunk.source_type,
            content_preview=chunk.content[:200],
            similarity=chunk.similarity,
            chunk_id=chunk.id,
            set=(chunk.metadata or {}).get("set"),
            rule_codes=sorted(extract_rule_codes(chunk.content)),
        )
        for chunk in chunks
    ]

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

    latency_ms = round((time.time() - t0) * 1000)

    confidence = round(semantic_confidence, 4) if citations else 0.0
    if has_exact_card_match and citations:
        confidence = 1.0

    response = QueryResponse(
        answer=answer,
        citations=citations,
        latency_ms=latency_ms,
        cache_hit=False,
        confidence=confidence,
    )

    # Store in cache (non-blocking; errors are swallowed in set_cached)
    set_cached(
        cache_key,
        json.dumps({"answer": answer, "citations": [c.model_dump() for c in citations], "confidence": confidence}),
        ttl=settings.cache_ttl_s,
    )

    logger.info(
        "query.complete",
        query_id=query_id,
        latency_ms=latency_ms,
        cache_hit=False,
        model=settings.llm_model or settings.gemini_model,
        confidence=confidence,
    )

    return response
