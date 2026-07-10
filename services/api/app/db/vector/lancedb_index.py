"""LanceDB vector-index adapter (optional).

Requires `lancedb`. Embedded/serverless columnar vector store — good for local or
single-node deployments. Tenant isolation is a `where` predicate on every search;
deletion removes the row. Import-guarded (see the Qdrant adapter for the pattern).

Governance contract: see `app/db/vector/base.py`.
"""

from __future__ import annotations

from .base import VectorIndex, VectorMatch


class LanceDBVectorIndex(VectorIndex):
    name = "lancedb"

    def __init__(self, *, uri: str, table: str = "memoryops") -> None:
        self._table_name = table
        self._db = None
        try:
            import lancedb

            self._db = lancedb.connect(uri)
        except Exception:  # noqa: BLE001 - optional dependency / bad uri
            self._db = None

    def available(self) -> bool:
        return self._db is not None

    def _table(self):
        if self._db is None:
            return None
        try:
            return self._db.open_table(self._table_name)
        except Exception:  # noqa: BLE001 - table not created yet
            return None

    def upsert(self, tenant_id: str, user_id: str, memory_id: str, embedding: list[float]) -> None:
        if self._db is None:
            return
        if not embedding:
            self.delete(tenant_id, user_id, memory_id)
            return
        row = {
            "id": memory_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "vector": list(embedding),
        }
        table = self._table()
        if table is None:
            self._db.create_table(self._table_name, data=[row])
            return
        # Replace-by-id: delete then add keeps upsert idempotent across versions.
        table.delete(f"id = '{memory_id}'")
        table.add([row])

    def delete(self, tenant_id: str, user_id: str, memory_id: str) -> None:
        table = self._table()
        if table is None:
            return
        table.delete(f"id = '{memory_id}' AND tenant_id = '{tenant_id}' AND user_id = '{user_id}'")

    def query(
        self, tenant_id: str, user_id: str, embedding: list[float], *, limit: int = 50
    ) -> list[VectorMatch]:
        table = self._table()
        if table is None or not embedding:
            return []
        try:
            rows = (
                table.search(list(embedding))
                .where(f"tenant_id = '{tenant_id}' AND user_id = '{user_id}'")
                .limit(limit)
                .to_list()
            )
        except Exception:  # noqa: BLE001 - degrade to keyword-only
            return []
        out: list[VectorMatch] = []
        for r in rows:
            # LanceDB returns L2 `_distance`; map to a descending similarity.
            dist = float(r.get("_distance", 0.0))
            out.append(VectorMatch(memory_id=r.get("id", ""), score=1.0 / (1.0 + dist)))
        return out
