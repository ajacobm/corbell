"""Factory for creating EmbeddingStore instances by backend name.

To add a new backend:
    1. Create a class that implements :class:`~corbell.core.embeddings.base.EmbeddingStore`.
    2. Add an ``elif backend == "<name>":`` branch below.
    3. Users opt in via ``storage.embeddings.backend: <name>`` in workspace.yaml.
"""

from __future__ import annotations

from pathlib import Path

from corbell.core.embeddings.base import EmbeddingStore

_SUPPORTED_BACKENDS = ("sqlite",)


def get_embedding_store(backend: str, db_path: Path) -> EmbeddingStore:
    """Return an :class:`EmbeddingStore` for the requested backend.

    Args:
        backend: Backend identifier string (e.g. ``"sqlite"``).
        db_path: Path to the storage file / directory.

    Returns:
        A concrete :class:`EmbeddingStore` instance.

    Raises:
        ValueError: If ``backend`` is not a recognised backend name.
    """
    backend = backend.lower().strip()

    if backend == "sqlite":
        from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore
        return SQLiteEmbeddingStore(db_path)

    # ------------------------------------------------------------------ #
    # Future backends — add branches here, e.g.:                          #
    #   elif backend == "kuzu":                                            #
    #       from corbell.core.embeddings.kuzu_store import KuzuEmbeddingStore
    #       return KuzuEmbeddingStore(db_path)                            #
    # ------------------------------------------------------------------ #

    raise ValueError(
        f"Unknown embedding backend: {backend!r}. "
        f"Supported backends: {', '.join(_SUPPORTED_BACKENDS)}. "
        f"Set 'storage.embeddings.backend' in workspace.yaml."
    )
