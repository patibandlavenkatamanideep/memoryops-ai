"""Repository factory — selects the backend from settings (ADR-001)."""

from __future__ import annotations

from functools import lru_cache

from ..core.config import get_settings
from .repository import Repository


@lru_cache
def get_repository() -> Repository:
    settings = get_settings()
    if settings.storage == "postgres":
        # Lazy import so the in-memory backend needs no sqlalchemy/pgvector.
        from .postgres_repo import PostgresRepository

        return PostgresRepository()
    from .memory_repo import InMemoryRepository

    return InMemoryRepository(vector_index=_build_vector_index(settings))


def _build_vector_index(settings):
    """Select the configured vector backend (v1.7, ADR-021).

    Default "memory" stays dependency-free. An external backend is used only when
    selected *and* reachable; if its client isn't installed or the server is down,
    we fall back to the in-memory index so retrieval never hard-fails (invariant #4).
    """
    from .vector import InMemoryVectorIndex, create_vector_index

    if settings.vector_index == "memory":
        return InMemoryVectorIndex()
    index = create_vector_index(
        settings.vector_index,
        url=settings.vector_index_url or None,
        uri=settings.vector_index_uri,
        api_key=settings.vector_index_api_key or None,
        collection=settings.vector_index_collection,
    )
    return index if index.available() else InMemoryVectorIndex()
