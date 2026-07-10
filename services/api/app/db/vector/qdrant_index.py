"""Qdrant vector-index adapter (optional).

Requires `qdrant-client` and a reachable Qdrant instance. Tenant isolation is
enforced with a payload filter on every query (never a shared unfiltered search),
and deletion removes the point outright. Import-guarded: with no client installed,
`available()` is False and the factory refuses to select it, so the default
in-memory path is unaffected and offline tests never import Qdrant.

Governance contract: see `app/db/vector/base.py`.
"""

from __future__ import annotations

import uuid

from .base import VectorIndex, VectorMatch

_NAMESPACE = uuid.UUID("d7f0c4a2-1b3e-4c6a-9f2d-6e5a0b1c2d3e")


def _point_id(tenant_id: str, user_id: str, memory_id: str) -> str:
    # Deterministic UUID so re-upsert replaces the same point; scope-salted so ids
    # never collide across tenants even if a memory_id repeats.
    return str(uuid.uuid5(_NAMESPACE, f"{tenant_id}/{user_id}/{memory_id}"))


class QdrantVectorIndex(VectorIndex):
    name = "qdrant"

    def __init__(self, *, url: str, api_key: str | None = None, collection: str = "memoryops") -> None:
        self._collection = collection
        self._client = None
        try:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=url, api_key=api_key)
        except Exception:  # noqa: BLE001 - optional dependency / unreachable server
            self._client = None

    def available(self) -> bool:
        return self._client is not None

    def _filter(self, tenant_id: str, user_id: str):
        from qdrant_client import models

        return models.Filter(
            must=[
                models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)),
                models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
            ]
        )

    def upsert(self, tenant_id: str, user_id: str, memory_id: str, embedding: list[float]) -> None:
        if self._client is None:
            return
        if not embedding:
            self.delete(tenant_id, user_id, memory_id)
            return
        from qdrant_client import models

        self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=_point_id(tenant_id, user_id, memory_id),
                    vector=list(embedding),
                    payload={"tenant_id": tenant_id, "user_id": user_id, "memory_id": memory_id},
                )
            ],
        )

    def delete(self, tenant_id: str, user_id: str, memory_id: str) -> None:
        if self._client is None:
            return
        from qdrant_client import models

        self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=[_point_id(tenant_id, user_id, memory_id)]),
        )

    def query(
        self, tenant_id: str, user_id: str, embedding: list[float], *, limit: int = 50
    ) -> list[VectorMatch]:
        if self._client is None or not embedding:
            return []
        try:
            hits = self._client.search(
                collection_name=self._collection,
                query_vector=list(embedding),
                query_filter=self._filter(tenant_id, user_id),
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - degrade to keyword-only on any backend error
            return []
        return [
            VectorMatch(memory_id=h.payload.get("memory_id", ""), score=float(h.score))
            for h in hits
            if h.payload
        ]
