"""VectorIndex conformance suite (v1.7, ADR-021).

`assert_vector_index_contract` is the reusable proof every backend must pass:
tenant isolation, deletion non-reappearance, and ranking. It runs here against the
in-memory index; the same function can be pointed at a live Qdrant/LanceDB/Weaviate
adapter in an integration environment to certify a new backend before it ships.
"""

from __future__ import annotations

from app.db.memory_repo import InMemoryRepository
from app.db.vector import InMemoryVectorIndex, VectorIndex, create_vector_index


def assert_vector_index_contract(index: VectorIndex) -> None:
    """Exercise the governance contract on any VectorIndex implementation."""
    assert index.available()

    # Two tenants + a second user in tenant t1, all with distinct vectors.
    index.upsert("t1", "u1", "m_a", [1.0, 0.0, 0.0])
    index.upsert("t1", "u1", "m_b", [0.0, 1.0, 0.0])
    index.upsert("t2", "u1", "m_x", [1.0, 0.0, 0.0])  # other tenant, identical vector
    index.upsert("t1", "u2", "m_y", [1.0, 0.0, 0.0])  # other user, identical vector

    # 1. Tenant/user isolation — a query only ever sees its own scope.
    hits = index.query("t1", "u1", [1.0, 0.0, 0.0], limit=10)
    ids = {h.memory_id for h in hits}
    assert ids <= {"m_a", "m_b"}
    assert "m_x" not in ids and "m_y" not in ids

    # 2. Ranking — the closest vector ranks first.
    assert hits[0].memory_id == "m_a"

    # 3. Deletion — a removed id can never be returned again.
    index.delete("t1", "u1", "m_a")
    ids_after = {h.memory_id for h in index.query("t1", "u1", [1.0, 0.0, 0.0], limit=10)}
    assert "m_a" not in ids_after

    # 4. Empty embedding (embedding failure) → no matches, never an error.
    assert index.query("t1", "u1", [], limit=10) == []

    # 5. Upsert with an empty vector removes the id (a memory with no vector
    #    is not searchable).
    index.upsert("t1", "u1", "m_b", [])
    assert not {h.memory_id for h in index.query("t1", "u1", [0.0, 1.0, 0.0], limit=10)}


def test_in_memory_index_conformance():
    assert_vector_index_contract(InMemoryVectorIndex())


def test_factory_defaults_to_memory():
    idx = create_vector_index("memory")
    assert isinstance(idx, InMemoryVectorIndex) and idx.available()


def test_factory_rejects_unknown_backend():
    import pytest

    with pytest.raises(ValueError):
        create_vector_index("pinecone-typo")


def test_external_adapters_import_guarded():
    # Selecting an external backend never raises at construction; when its client
    # isn't installed the index simply reports unavailable (→ keyword-only).
    for name in ("qdrant", "lancedb", "weaviate"):
        idx = create_vector_index(name)
        assert idx.name == name
        assert idx.available() is False  # no client / server in the test env


# ── the repository actually uses the seam (load-bearing, not decorative) ─────────
def test_repository_delegates_similarity_to_injected_index():
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    class _SpyIndex(InMemoryVectorIndex):
        def __init__(self) -> None:
            super().__init__()
            self.queried = 0

        def query(self, *a, **kw):
            self.queried += 1
            return super().query(*a, **kw)

    spy = _SpyIndex()
    repo = InMemoryRepository(vector_index=spy)
    m = StoredMemory(
        tenant_id="t1", user_id="u1", memory_type=MemoryType.semantic,
        content="prefers dark mode", importance=5, confidence=0.9,
        sensitivity=Sensitivity.low, status=Status.active,
        source=Source(kind="chat"), embedding=[1.0, 0.0, 0.0],
    )
    repo.create_memory(m)
    out = repo.search_candidates("t1", "u1", [1.0, 0.0, 0.0], limit=5)
    assert spy.queried == 1
    assert out and out[0][0].id == m.id and out[0][1] > 0.9

    # Deleting removes the vector, so it can no longer be a scored candidate.
    repo.soft_delete("t1", "u1", m.id)
    assert repo.search_candidates("t1", "u1", [1.0, 0.0, 0.0], limit=5) == []
