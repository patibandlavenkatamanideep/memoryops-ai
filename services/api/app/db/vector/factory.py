"""Vector-index factory — select a backend by name, degrade safely.

`memory` is always available and dependency-free. External backends are constructed
only when explicitly selected; if their client isn't installed or the server is
unreachable, construction returns an index whose `available()` is False so callers
can fall back to keyword-only retrieval instead of failing (invariant #4).
"""

from __future__ import annotations

from .base import VectorIndex
from .memory_index import InMemoryVectorIndex

_EXTERNAL = {"qdrant", "lancedb", "weaviate"}


def create_vector_index(name: str, **kwargs) -> VectorIndex:
    name = (name or "memory").lower()
    if name == "memory":
        return InMemoryVectorIndex()
    if name == "qdrant":
        from .qdrant_index import QdrantVectorIndex

        return QdrantVectorIndex(
            url=kwargs.get("url", "http://localhost:6333"),
            api_key=kwargs.get("api_key"),
            collection=kwargs.get("collection", "memoryops"),
        )
    if name == "lancedb":
        from .lancedb_index import LanceDBVectorIndex

        return LanceDBVectorIndex(uri=kwargs.get("uri", "./.lancedb"), table=kwargs.get("table", "memoryops"))
    if name == "weaviate":
        from .weaviate_index import WeaviateVectorIndex

        return WeaviateVectorIndex(
            url=kwargs.get("url", "http://localhost:8080"),
            api_key=kwargs.get("api_key"),
            collection=kwargs.get("collection", "MemoryOps"),
        )
    raise ValueError(f"unknown vector index '{name}'; expected memory or one of {sorted(_EXTERNAL)}")
