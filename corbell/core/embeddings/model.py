"""Embedding model interface + SentenceTransformers implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List


class EmbeddingModel(ABC):
    """Abstract embedding model interface."""

    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        """Encode a list of texts into embedding vectors.

        Args:
            texts: List of text strings to encode.

        Returns:
            List of float vectors (one per input text).
        """
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        ...


class SentenceTransformerModel(EmbeddingModel):
    """Wraps ``sentence-transformers`` with lazy loading.

    Uses ``all-MiniLM-L6-v2`` by default (384-dim, fast, no API key).
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None  # lazy-loaded

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(f"sentence-transformers/{self.model_name}")
        return self._model

    def encode(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()
        vecs = model.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    @property
    def dimension(self) -> int:
        return self._get_model().get_sentence_embedding_dimension()
