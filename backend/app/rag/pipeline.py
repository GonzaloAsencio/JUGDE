import json
import time
import uuid

from app.cache import get_cached, make_cache_key, set_cached
from app.config import Settings
from app.observability import get_logger
from app.rag.embedder import Embedder
from app.rag.generation import build_prompt, call_gemini, post_gen_validate
from app.rag.retrieval import hybrid_search
from app.rag.schemas import Citation, QueryResponse

logger = get_logger(__name__)

_NO_INFO_ANSWER = "No tengo información suficiente para responder esa pregunta con las reglas disponibles."


async def answer_question(
    question: str,
    embedder: Embedder,
    db_pool,
    gemini,
    settings: Settings,
) -> QueryResponse:
    """Orchestrate embed -> retrieve -> generate with cache, tracing, and post-gen validation."""
    t0 = time.time()
    query_id = str(uuid.uuid4())

    corpus_version = settings.corpus_version or "latest"
    cache_key = make_cache_key(question, corpus_version)

    # Cache check — runs after Pydantic validation + rate limit (see ADR-1)
    cached_raw = await get_cached(cache_key)
    if cached_raw is not None:
        try:
            cached_data = json.loads(cached_raw)
            latency_ms = round((time.time() - t0) * 1000)
            logger.info(
                "query.complete",
                query_id=query_id,
                latency_ms=latency_ms,
                cache_hit=True,
                model=settings.gemini_model,
            )
            return QueryResponse(**{**cached_data, "cache_hit": True, "latency_ms": latency_ms})
        except Exception:
            pass  # Corrupt cache entry — fall through to generation

    embedding = embedder.encode(question)

    chunks = hybrid_search(
        db_pool, embedding, question, corpus_version,
        top_k=settings.top_k,
        top_k_fetch=settings.top_k_fetch,
        rrf_k=settings.rrf_k,
    )

    retrieval_ms = round((time.time() - t0) * 1000)

    if not chunks:
        latency_ms = retrieval_ms
        logger.info(
            "query.complete",
            query_id=query_id,
            latency_ms=latency_ms,
            cache_hit=False,
            model=settings.gemini_model,
        )
        return QueryResponse(
            answer=_NO_INFO_ANSWER,
            citations=[],
            latency_ms=latency_ms,
            cache_hit=False,
        )

    prompt = build_prompt(question, chunks)
    answer = call_gemini(
        gemini,
        prompt,
        temperature=settings.gemini_temperature,
        timeout_s=settings.gemini_timeout_s,
    )

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

    response = QueryResponse(
        answer=answer,
        citations=citations,
        latency_ms=latency_ms,
        cache_hit=False,
    )

    # Store in cache (non-blocking; errors are swallowed in set_cached)
    await set_cached(
        cache_key,
        json.dumps({"answer": answer, "citations": [c.model_dump() for c in citations]}),
        ttl=settings.cache_ttl_s,
    )

    logger.info(
        "query.complete",
        query_id=query_id,
        latency_ms=latency_ms,
        cache_hit=False,
        model=settings.gemini_model,
    )

    return response
