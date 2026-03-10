"""Abstract base class for embedding stores.

All concrete embedding backends (SQLite, KuzuDB, etc.) must implement
this interface so the CLI and callers are decoupled from any specific
storage implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from corbell.core.embeddings.extractor import EmbeddingRecord


class EmbeddingStore(ABC):
    """Abstract interface for code embedding storage and retrieval.

    Mirrors the pluggable design of :class:`~corbell.core.graph.schema.GraphStore`.
    Implement this class to add a new embedding backend (e.g. KuzuDB, pgvector).
    """

    @abstractmethod
    def upsert_batch(self, records: List[EmbeddingRecord]) -> None:
        """Insert or replace a batch of embedding records.

        Args:
            records: Records with populated ``embedding`` vectors to store.
        """
        ...

    @abstractmethod
    def query(
        self,
        query_embedding: List[float],
        service_ids: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[EmbeddingRecord]:
        """Return top-K most similar records by cosine similarity.

        Args:
            query_embedding: Query vector (same dimensionality as stored embeddings).
            service_ids: Restrict search to these service IDs. ``None`` means all.
            top_k: Number of results to return, ordered by descending similarity.

        Returns:
            List of :class:`~corbell.core.embeddings.extractor.EmbeddingRecord`
            ordered by descending similarity score.
        """
        ...

    @abstractmethod
    def count(self, service_id: Optional[str] = None) -> int:
        """Return the number of stored chunks.

        Args:
            service_id: Count only chunks for this service. ``None`` means all.
        """
        ...

    @abstractmethod
    def clear(self, service_id: Optional[str] = None) -> None:
        """Delete stored chunks.

        Args:
            service_id: Delete only chunks for this service. ``None`` deletes all.
        """
        ...
