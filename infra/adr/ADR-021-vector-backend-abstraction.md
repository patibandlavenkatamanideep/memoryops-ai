# ADR-021 — Storage / Vector Backend Abstraction

- Status: Accepted (v1.7)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-001 (repository pattern), ADR-006 (pgvector / RLS retrieval),
  ADR-017 (admission gate), ADR-018 (tombstone lineage)

## Context

MemoryOps already had a `Repository` abstraction with two backends (in-memory,
Postgres+pgvector). To be adoptable it needs to run on whatever vector store a team
already operates — Qdrant, LanceDB, Weaviate, Pinecone — **without** each backend
re-implementing (or quietly weakening) tenant isolation, the deletion guarantee,
context admission, provenance, or audit. The failure mode to avoid is "portability by
moving governance into the vector DB", where every store enforces isolation
differently and deletion means different things.

## Decision

Split retrieval into an authoritative repository and a narrow, swappable
**`VectorIndex`** seam (`app/db/vector/`).

- **The repository stays authoritative.** Memory metadata, governance/consent,
  tombstone lineage, audit, and worker runtime remain in the `Repository`
  (in-memory / Postgres). It is still the single enforcement point for isolation and
  deletion.
- **`VectorIndex` abstracts only ANN search** — `upsert` / `delete` / `query` /
  `available`, all scoped by `(tenant_id, user_id)`. It stores **ids + embeddings
  only**, never content/provenance/consent/lineage. After it returns candidate ids,
  the repository and admission gate re-check every one, so a stale index entry cannot
  leak content (defense-in-depth).
- **A written contract + conformance suite.** `base.py` states the four rules
  (isolation, deletion, no-bypass, graceful-degradation);
  `assert_vector_index_contract` proves them and can be pointed at a live backend to
  certify it before shipping.
- **The in-memory backend actually uses the seam.** `InMemoryRepository` maintains an
  `InMemoryVectorIndex` across create/update/delete/compaction and delegates
  similarity to it — so the abstraction is load-bearing, not decorative, and every
  existing retrieval test exercises it.
- **External adapters are optional + import-guarded.** Qdrant, LanceDB, Weaviate ship
  as adapters that construct only when selected; with no client installed
  `available()` is `False` and the factory falls back to the in-memory index. This
  mirrors how optional LLM/embedding providers already work — offline tests never
  import them, no new hard dependency.
- **Selected via config**: `MEMORYOPS_VECTOR_INDEX=memory|qdrant|lancedb|weaviate`
  (default `memory`) plus connection knobs.

## Consequences

- New vector stores plug in behind one small interface; governance is inherited, not
  re-implemented. Adding Pinecone is a sibling adapter of ~60 lines.
- Backward compatible: default is unchanged, all 316 prior tests pass; +5 conformance
  tests. No schema or API change.
- An unreachable external backend degrades to keyword-only / in-memory rather than
  failing requests (invariant #4).
- Cost: the in-memory index is rebuilt-free (maintained incrementally) and adds a
  dict lookup per write; external backends add their client's network cost.

## Out of scope (later)

- A Postgres repository composed with an *external* vector index (the composition
  pattern is documented; pgvector remains the native Postgres path).
- Live integration CI against hosted vector stores (the conformance suite is the
  certification hook; running it against real servers is an ops task).
- Cross-backend migration tooling / dual-write.
