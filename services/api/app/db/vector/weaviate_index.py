"""Weaviate vector-index adapter (optional).

Requires `weaviate-client` (v4) and a reachable Weaviate instance. Tenant isolation
is a `where` filter on tenant_id/user_id for every query; deletion removes the
object. Import-guarded (see the Qdrant adapter for the pattern). Pinecone follows the
same shape — a namespaced upsert/delete/query with a metadata filter — and can be
added as a sibling adapter.

Governance contract: see `app/db/vector/base.py`.
"""

from __future__ import annotations

import uuid

from .base import VectorIndex, VectorMatch

_NAMESPACE = uuid.UUID("b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e")


def _object_id(tenant_id: str, user_id: str, memory_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{tenant_id}/{user_id}/{memory_id}"))


class WeaviateVectorIndex(VectorIndex):
    name = "weaviate"

    def __init__(self, *, url: str, api_key: str | None = None, collection: str = "MemoryOps") -> None:
        self._collection_name = collection
        self._client = None
        try:
            import weaviate

            if api_key:
                self._client = weaviate.connect_to_weaviate_cloud(
                    cluster_url=url,
                    auth_credentials=weaviate.classes.init.Auth.api_key(api_key),
                )
            else:
                self._client = weaviate.connect_to_local(url)
        except Exception:  # noqa: BLE001 - optional dependency / unreachable
            self._client = None

    def available(self) -> bool:
        return self._client is not None

    def _collection(self):
        if self._client is None:
            return None
        try:
            return self._client.collections.get(self._collection_name)
        except Exception:  # noqa: BLE001
            return None

    def upsert(self, tenant_id: str, user_id: str, memory_id: str, embedding: list[float]) -> None:
        if not embedding:
            self.delete(tenant_id, user_id, memory_id)
            return
        col = self._collection()
        if col is None:
            return
        col.data.insert(
            uuid=_object_id(tenant_id, user_id, memory_id),
            properties={"tenant_id": tenant_id, "user_id": user_id, "memory_id": memory_id},
            vector=list(embedding),
        )

    def delete(self, tenant_id: str, user_id: str, memory_id: str) -> None:
        col = self._collection()
        if col is None:
            return
        col.data.delete_by_id(_object_id(tenant_id, user_id, memory_id))

    def query(
        self, tenant_id: str, user_id: str, embedding: list[float], *, limit: int = 50
    ) -> list[VectorMatch]:
        col = self._collection()
        if col is None or not embedding:
            return []
        try:
            from weaviate.classes.query import Filter, MetadataQuery

            res = col.query.near_vector(
                near_vector=list(embedding),
                limit=limit,
                filters=Filter.by_property("tenant_id").equal(tenant_id)
                & Filter.by_property("user_id").equal(user_id),
                return_metadata=MetadataQuery(distance=True),
            )
        except Exception:  # noqa: BLE001 - degrade to keyword-only
            return []
        out: list[VectorMatch] = []
        for o in res.objects:
            dist = float(getattr(o.metadata, "distance", 0.0) or 0.0)
            out.append(
                VectorMatch(memory_id=o.properties.get("memory_id", ""), score=1.0 - dist)
            )
        return out
