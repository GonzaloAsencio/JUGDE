"""Cross-encoder reranker for the semantic retrieval pool (design D2).

Lazy singleton — DIFFERENT from Embedder on purpose. Embedder is loaded
eagerly at startup because it is always needed; enable_reranker defaults to
False, so eager loading here would cost ~80MB RAM on every deploy for a
disabled feature. First query with the flag on pays the cold-load cost once.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.observability import get_logger
from app.rag.retrieval import Chunk

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

logger = get_logger(__name__)

_model: "CrossEncoder | None" = None


def _get_model(model_name: str) -> "CrossEncoder":
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415

        _model = CrossEncoder(model_name)
    return _model


def rerank(
    query: str,
    chunks: list[Chunk],
    top_k: int,
    *,
    model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
) -> list[Chunk]:
    """Reorder *chunks* by cross-encoder relevance to *query*, return top_k.

    Never-raise: any failure (model load, predict) degrades to the input
    order, truncated to top_k — a reranker error must never break a query.
    Empty *chunks* returns [] without touching the model.
    """
    if not chunks:
        return []
    try:
        model = _get_model(model_name)
        scores = model.predict([(query, c.content) for c in chunks])
        ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
        return [c for c, _ in ranked[:top_k]]
    except Exception as e:
        logger.warning("reranker.failed", error=str(e))
        return chunks[:top_k]
