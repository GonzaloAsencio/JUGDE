from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class Embedder:
    """Thin wrapper around SentenceTransformer. Never loads the model at import time."""

    def __init__(self, model: SentenceTransformer) -> None:
        self._model = model

    @classmethod
    def load(cls, model_name: str = "BAAI/bge-m3") -> Embedder:
        """Eagerly load SentenceTransformer. ~5-10s. Call ONCE at startup."""
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        return cls(SentenceTransformer(model_name))

    def encode(self, text: str) -> list[float]:
        """Return L2-normalized 1024-dim vector as list[float]."""
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()
