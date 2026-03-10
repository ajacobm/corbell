"""Corbell embeddings module."""

from corbell.core.embeddings.base import EmbeddingStore
from corbell.core.embeddings.factory import get_embedding_store

__all__ = ["EmbeddingStore", "get_embedding_store"]
