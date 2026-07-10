# Storage backend abstraction

MemoryOps is portable across vector stores **without weakening any governance
guarantee** (v1.7, [ADR-021](../infra/adr/ADR-021-vector-backend-abstraction.md)).

The trick is to separate two concerns that are usually tangled:

- **The authoritative `Repository`** owns governed state — memory metadata,
  governance/consent, tombstone lineage, audit, worker runtime. It stays the single
  place tenant isolation and the deletion guarantee are enforced.
- **The `VectorIndex`** owns the one store-specific thing: approximate
  nearest-neighbour search over embeddings. This is the swappable part.

Swapping the vector store never moves governance out of MemoryOps — the index holds
**only ids + embeddings**, never content, provenance, consent, or lineage. After the
index returns candidate ids, the repository and the [Context Admission Gate](context-admission-gate.md)
re-check every one, so a stale index entry can never leak content.

## The contract every backend upholds

`app/db/vector/base.py` defines it; `tests/test_vector_index.py::assert_vector_index_contract`
proves it. Any backend — in-memory, Qdrant, LanceDB, Weaviate, Pinecone — must:

1. **Tenant isolation (#1)** — `query(tenant, user, …)` returns only vectors
   `upsert`-ed under the same `(tenant_id, user_id)`, even if a cross-tenant vector is
   numerically closer.
2. **Deletion (#2)** — after `delete(...)` (or re-`upsert` with an empty vector) an id
   can never be returned by `query` again. The vector is removed, not tombstoned.
3. **No governance bypass** — ids + embeddings only; everything governed stays in the
   repository, which re-checks admission after the index returns candidates.
4. **Graceful degradation (#4)** — `query` returns `[]` on an unavailable backend so
   retrieval degrades to keyword-only instead of failing the request.

To certify a new backend, point `assert_vector_index_contract` at a live instance in an
integration environment.

## Backends

| Backend | `MEMORYOPS_VECTOR_INDEX` | Dependency | Notes |
| --- | --- | --- | --- |
| In-memory cosine | `memory` (default) | none | dev/tests; also backs the default repo |
| pgvector | (via `MEMORYOPS_STORAGE=postgres`) | sqlalchemy + pgvector | native `<=>` search under RLS |
| Qdrant | `qdrant` | `qdrant-client` | payload-filtered search, point delete |
| LanceDB | `lancedb` | `lancedb` | embedded/serverless columnar store |
| Weaviate | `weaviate` | `weaviate-client` (v4) | `where`-filtered `near_vector` |
| Pinecone | — | `pinecone-client` | same shape (namespaced upsert/query); add as a sibling adapter |

External backends are **import-guarded**: with no client installed, `available()` is
`False`, and the factory falls back to the in-memory index — so the default path never
imports them and offline tests never touch them.

## Selecting a backend

```bash
# Qdrant
export MEMORYOPS_VECTOR_INDEX=qdrant
export MEMORYOPS_VECTOR_INDEX_URL=http://localhost:6333
export MEMORYOPS_VECTOR_INDEX_API_KEY=...          # optional
export MEMORYOPS_VECTOR_INDEX_COLLECTION=memoryops

# LanceDB (embedded)
export MEMORYOPS_VECTOR_INDEX=lancedb
export MEMORYOPS_VECTOR_INDEX_URI=./.lancedb

# Weaviate
export MEMORYOPS_VECTOR_INDEX=weaviate
export MEMORYOPS_VECTOR_INDEX_URL=http://localhost:8080
```

If the selected backend can't be reached at startup, MemoryOps logs and uses the
in-memory index rather than failing — retrieval quality degrades, governance does not.

## Adding a backend

1. Implement `VectorIndex` (`upsert` / `delete` / `query` / `available`), scoping every
   operation by `(tenant_id, user_id)` and removing vectors on delete.
2. Register it in `app/db/vector/factory.py`.
3. Run `assert_vector_index_contract(YourIndex(...))` against a live instance.

That's the whole surface — governance is not your backend's job; the repository keeps it.
