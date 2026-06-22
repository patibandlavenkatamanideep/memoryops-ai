# Deletion Verification — Logical vs Physical Forgetting (v0.6)

> Part of the [background lifecycle workers](background-lifecycle-workers.md).
> Decision records: [ADR-005](../infra/adr/ADR-005-deletion-guarantee.md),
> [ADR-010](../infra/adr/ADR-010-background-memory-lifecycle-workers.md).
> Security context: [security.md](security.md).

The deletion guarantee (**invariant #2**: `status='deleted'` rows are never
retrieved) is enforced at write/read time by the repository. The deletion
verification worker provides **continuous, auditable evidence** that the guarantee
still holds over time — and catches regressions safely if it ever does not.

## What it checks

For each soft-deleted memory in a `(tenant_id, user_id)` scope, the worker
confirms the id does **not** appear in any reachable read surface:

1. active retrieval — `retrieve_active`,
2. default memory listing — `list_memories` (excludes deleted),
3. the vector candidate path — `search_candidates` (empty embedding degrades to
   "active rows at similarity 0", exactly the set a deleted id must stay out of).

It is **read-only**. It never mutates, never deletes, and never resurrects a row.

## Outcomes

- **Pass** — every deleted id is absent from all three surfaces. The worker
  records a single `deletion_verification_passed` event with the verified count.
- **Finding** — a deleted id leaks into a surface. The worker records a
  `deletion_verification_failed` event (with the leaking `surfaces`, by id only),
  sets the run status to `completed_with_findings`, and increments `error_count`.
  The runner exits non-zero so a scheduled run flags the regression — **without**
  the worker changing any data.

Audit metadata is content-free: memory ids, surface names, and counts only.

## Logical deletion vs physical / vector purge

| | Logical deletion (today) | Physical / vector purge (future) |
|--|--|--|
| Mechanism | `status='deleted'` soft delete; repository excludes from all reads | Remove the row and its vector from storage / the ANN index |
| Guarantee | Never retrieved (invariant #2) | Bytes no longer present |
| Verified by | **this worker** | the [deletion compaction worker](deletion-compaction.md) (v0.7) |
| Reversible | Yes (forensics/audit can still see it) | No — payload cleared (tombstone kept) |

v0.6 verifies **logical** forgetting. v0.7 adds **content/vector compaction** on
top of it (see below). Neither claims cryptographic erasure or physical disk/page
byte reclamation — those remain staged.

## v0.7: deletion compaction + vector purge verification

The [deletion compaction worker](deletion-compaction.md) now clears a soft-deleted
memory's content + vector material (after a retention window), preserves the
governance tombstone + audit trail, and **verifies** the purge fail-closed (see
[vector-purge-verification.md](vector-purge-verification.md)). It:

- runs only on rows already `status='deleted'` and past retention;
- is tenant scoped, idempotent, and fully audited (`memory_content_compacted`,
  `memory_vector_purge_verified`, `memory_purge_tombstone_preserved`, …);
- never resurrects deleted memory and never runs on the chat path.

Logical verification (this worker) + compaction verification (v0.7) together are
the auditable bridge: deleted memory is provably unreachable **and** its payload is
provably cleared, with evidence on every run. Crypto-shred and physical
disk/index reclamation remain future work (ADR-011).
