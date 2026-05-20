import json
import re
import time
import uuid

from app.cache import get_cached, make_cache_key, set_cached
from app.config import Settings
from app.observability import get_logger
from app.rag.embedder import Embedder
from app.rag.generation import call_llm, post_gen_validate, rewrite_query_for_retrieval
from app.rag.retrieval import hybrid_search, tagged_lookup
from app.rag.schemas import Citation, QueryResponse

logger = get_logger(__name__)

_NO_INFO_ANSWER = "No tengo información suficiente para responder esa pregunta con las reglas disponibles."
_TAG_RE = re.compile(r"@(\w+)", re.UNICODE)


def _extract_tags(question: str) -> tuple[str, list[str]]:
    """Extract @tags from question. Returns (clean_question, [tags_lowercase])."""
    tags = _TAG_RE.findall(question)
    clean = _TAG_RE.sub("", question).strip()
    return clean, [t.lower() for t in tags]


async def answer_question(
    question: str,
    embedder: Embedder,
    db_pool,
    llm_client,
    settings: Settings,
    card_mentions: list[str] | None = None,
) -> QueryResponse:
    """Orchestrate embed -> retrieve -> generate with cache, tracing, and post-gen validation."""
    t0 = time.time()
    query_id = str(uuid.uuid4())

    corpus_version = settings.corpus_version or "latest"
    cache_key = make_cache_key(question, corpus_version, card_mentions)

    # Cache check — runs after Pydantic validation + rate limit (see ADR-1)
    cached_raw = await get_cached(cache_key)
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

    clean_question, tags = _extract_tags(question)
    retrieval_query = rewrite_query_for_retrieval(clean_question or question, settings)
    embedding = embedder.encode(retrieval_query)

    tagged_chunks: list = []
    if tags:
        tagged_chunks = tagged_lookup(db_pool, tags, corpus_version)

    chunks = hybrid_search(
        db_pool, embedding, clean_question or question, corpus_version,
        top_k=settings.top_k,
        top_k_fetch=settings.top_k_fetch,
        rrf_k=settings.rrf_k,
    )

    if tagged_chunks:
        seen = {c.id for c in tagged_chunks}
        semantic = [c for c in chunks if c.id not in seen]
        chunks = tagged_chunks + semantic[:settings.top_k - len(tagged_chunks)]

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

    answer = call_llm(clean_question or question, chunks, settings, gemini_client=llm_client)

    citations = [
        Citation(
            section=chunk.section,
            source_type=chunk.source_type,
            content_preview=chunk.content[:200],
            similarity=chunk.similarity,
            chunk_id=chunk.id,
        )
        for chunk in chunks
    ]

    valid_ids = {chunk.id for chunk in chunks}
    answer, _ = post_gen_validate(answer, citations, valid_chunk_ids=valid_ids)

    latency_ms = round((time.time() - t0) * 1000)

    confidence = round(citations[0].similarity, 4) if citations else 0.0

    response = QueryResponse(
        answer=answer,
        citations=citations,
        latency_ms=latency_ms,
        cache_hit=False,
        confidence=confidence,
    )

    # Store in cache (non-blocking; errors are swallowed in set_cached)
    await set_cached(
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
