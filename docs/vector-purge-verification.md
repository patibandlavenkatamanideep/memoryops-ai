# Vector / Content Purge Verification (v0.7)

> Part of [deletion compaction](deletion-compaction.md).
> Decision record: [ADR-011](../infra/adr/ADR-011-physical-deletion-compaction-vector-purge.md).
> Code: `services/api/app/workers/vector_purge.py`.

Compaction *clears* a deleted memory's content + vector material. Verification
*proves* it. `verify_purged` answers, for one compacted memory:

1. Can it still appear in **active retrieval** (`retrieve_active`)?
2. Can it still appear in the **default listing** (`list_memories`)?
3. Can it still appear in the **vector candidate path** (`search_candidates`)?
4. Is its retrievable **content** actually cleared?
5. Is its **vector material** actually cleared?
6. Is the **governance tombstone** still present?

## Outcomes

| Result | Meaning |
|--------|---------|
| `pass` | absent from all surfaces; content + vector cleared; tombstone present |
| `fail` | reachable on a surface, OR material not cleared, OR tombstone missing, OR the verification path itself errored |
| `skipped` | not applicable |
| `not_supported` | backend genuinely cannot clear vector material (reserved; neither shipped backend hits this) |

## Fail-closed

Verification never silently passes. If a deleted/compacted id is still reachable,
if the content or embedding is still present, if the tombstone vanished, or if the
verification code path raises, the result is **`fail`**. The compaction worker
turns a `fail` into a `memory_vector_purge_failed` audit event and marks the run
`completed_with_findings` (the runner then exits non-zero).

## What "purge" honestly means here

This is the important, enterprise-safe distinction:

> **MemoryOps verifies application-level vector-candidate exclusion and
> repository-level vector/content material clearing.** Full database physical
> storage reclamation (page-level overwrite, ANN-index compaction) depends on the
> database / index engine and is documented as out of scope.

What is verified:

- **Application-level retrieval exclusion** — the id cannot surface through any
  repository read path a caller could use.
- **Repository-level material clearing** — `content`/`normalized_content` are
  empty, the embedding is empty (`[]` in-memory) / `NULL` (Postgres vector column),
  and the provenance excerpt is cleared.

What is **not** claimed:

- physical disk / database-page byte erasure;
- pgvector index storage reclamation (`VACUUM` / reindex);
- cryptographic erasure.

That boundary is deliberate and stated so the deletion claim stays precise. See
[deletion-compaction.md](deletion-compaction.md) and ADR-011.

## Tests

- `services/api/tests/test_vector_purge_verification.py` — pass, reachable-fail,
  content-not-cleared-fail, missing-tombstone-fail, fail-closed-on-error.
- `services/api/tests/test_deletion_compaction_worker.py` — end-to-end compaction
  + verification, leak detection, idempotency, tenant isolation.
