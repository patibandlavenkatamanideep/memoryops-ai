"""The pluggable vector-search seam (v1.7, ADR-021).

The full `Repository` owns governed state — metadata, governance, audit, worker
runtime — and stays authoritative. The one store-specific, swappable part of
retrieval is **approximate nearest-neighbour search over embeddings**, so that is
what a `VectorIndex` abstracts. Any backend (in-memory, pgvector, Qdrant, LanceDB,
Weaviate, Pinecone) must uphold the same governance contract:

1. **Tenant isolation (#1)** — `query(tenant, user, …)` returns *only* vectors that
   were `upsert`-ed under the same `(tenant_id, user_id)`. Cross-tenant vectors are
   never returned, even if numerically closer.
2. **Deletion (#2)** — once `delete(...)` (or a re-`upsert` with an empty vector) is
   called, that memory id can never be returned by `query` again. A backend must
   remove the vector, not merely tombstone it.
3. **No governance bypass** — the index holds *only* ids + embeddings, never memory
   content, provenance, consent, or lineage. Those stay in the authoritative
   repository, which re-checks admission after the index returns candidates
   (defense-in-depth: a stale index entry can never leak content).

Implementations are no-throw on `query` for a missing/misconfigured backend: they
return `[]` so retrieval degrades to keyword-only (invariant #4) rather than failing
the request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class VectorMatch:
    memory_id: str
    score: float  # cosine similarity in [-1, 1]; higher is closer


class VectorIndex(ABC):
    """Tenant/user-scoped nearest-neighbour index over memory embeddings."""

    #: short, stable identifier used in config + logs (e.g. "memory", "qdrant").
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """True when the backing store/client is importable and reachable enough to use."""
        ...

    @abstractmethod
    def upsert(self, tenant_id: str, user_id: str, memory_id: str, embedding: list[float]) -> None:
        """Add or replace the vector for `memory_id` in the `(tenant, user)` scope.

        An empty embedding removes the id (a memory with no vector is not searchable).
        """
        ...

    @abstractmethod
    def delete(self, tenant_id: str, user_id: str, memory_id: str) -> None:
        """Remove `memory_id` from the index so it can never be returned again."""
        ...

    @abstractmethod
    def query(
        self, tenant_id: str, user_id: str, embedding: list[float], *, limit: int = 50
    ) -> list[VectorMatch]:
        """Top-`limit` matches within the `(tenant, user)` scope, highest score first.

        Returns `[]` for an empty query embedding or an unavailable backend — callers
        degrade to keyword-only ranking rather than failing (invariant #4).
        """
        ...
