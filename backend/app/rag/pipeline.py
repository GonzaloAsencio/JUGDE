import time

from app.config import Settings
from app.rag.embedder import Embedder
from app.rag.generation import build_prompt, call_gemini
from app.rag.retrieval import vector_search
from app.rag.schemas import Citation, QueryResponse

_NO_INFO_ANSWER = "No tengo información suficiente para responder esa pregunta con las reglas disponibles."


def answer_question(
    question: str,
    embedder: Embedder,
    db_pool,
    gemini,
    settings: Settings,
) -> QueryResponse:
    """Orchestrate embed → retrieve → generate. Measures latency_ms."""
    t0 = time.time()

    embedding = embedder.encode(question)

    corpus_version = settings.corpus_version or "latest"
    chunks = vector_search(db_pool, embedding, corpus_version, settings.top_k)

    elapsed_ms = round((time.time() - t0) * 1000)

    if not chunks:
        return QueryResponse(
            answer=_NO_INFO_ANSWER,
            citations=[],
            latency_ms=elapsed_ms,
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
        )
        for chunk in chunks
    ]

    latency_ms = round((time.time() - t0) * 1000)

    return QueryResponse(answer=answer, citations=citations, latency_ms=latency_ms)
