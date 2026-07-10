"""In-process cosine vector index — the default, dependency-free backend.

Backs the in-memory repository and is the reference implementation of the
`VectorIndex` contract (tenant isolation + deletion). Scoped stores keep vectors
partitioned by `(tenant_id, user_id)` so a query can only ever see its own scope.
"""

from __future__ import annotations

from .base import VectorIndex, VectorMatch


class InMemoryVectorIndex(VectorIndex):
    name = "memory"

    def __init__(self) -> None:
        # {(tenant, user): {memory_id: embedding}}
        self._scopes: dict[tuple[str, str], dict[str, list[float]]] = {}

    def available(self) -> bool:
        return True

    def _scope(self, tenant_id: str, user_id: str) -> dict[str, list[float]]:
        return self._scopes.setdefault((tenant_id, user_id), {})

    def upsert(self, tenant_id: str, user_id: str, memory_id: str, embedding: list[float]) -> None:
        scope = self._scope(tenant_id, user_id)
        if embedding:
            scope[memory_id] = list(embedding)
        else:
            scope.pop(memory_id, None)  # no vector ⇒ not searchable

    def delete(self, tenant_id: str, user_id: str, memory_id: str) -> None:
        self._scope(tenant_id, user_id).pop(memory_id, None)

    def query(
        self, tenant_id: str, user_id: str, embedding: list[float], *, limit: int = 50
    ) -> list[VectorMatch]:
        if not embedding:
            return []
        from ...embeddings import cosine

        scope = self._scopes.get((tenant_id, user_id), {})
        matches = [
            VectorMatch(memory_id=mid, score=cosine(embedding, vec))
            for mid, vec in scope.items()
            if vec
        ]
        matches.sort(key=lambda m: m.score, reverse=True)
        return matches[:limit]
