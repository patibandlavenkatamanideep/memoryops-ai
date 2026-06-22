# Phase 13 (addendum) — Deletion Compaction + Vector Purge Verification

> Companion to [phase-12-background-lifecycle-workers.md](phase-12-background-lifecycle-workers.md)
> and [phase-11-security.md](phase-11-security.md). v0.7 extends the *Forget* arc
> from logical deletion verification to auditable content/vector compaction.
> Decision record:
> [ADR-011](../../infra/adr/ADR-011-physical-deletion-compaction-vector-purge.md).

**Question:** Once memory is soft-deleted and proven unreachable, how is its
content + vector material actually *cleared* — with evidence, without destroying
governance metadata, and without overclaiming physical/crypto erasure?

## MemoryOps mapping
A sixth lifecycle job — **deletion compaction** (`services/api/app/workers/
deletion_compaction.py`) — clears the content, normalized content, embedding/vector
material, and provenance excerpt of soft-deleted memory past a retention window,
preserving the governance tombstone (id, tenant/user, `status='deleted'`,
`deleted_at`, `source.kind`, audit trail). A fail-closed verifier
(`workers/vector_purge.py`) then proves the memory is unreachable and the material
was cleared. Additive repository methods (`list_deleted_for_compaction`,
`compact_deleted_memory`) keep the change isolated. See
[deletion-compaction.md](../deletion-compaction.md),
[vector-purge-verification.md](../vector-purge-verification.md).

## Gate (must be true to pass)
- Only `status='deleted'` rows are compacted; active/archived memory is never
  touched (invariant #1) and deleted memory is never resurrected/reactivated
  (invariant #2).
- Compaction clears retrievable content + vector material and clears the
  provenance excerpt, while preserving the tombstone + audit trail.
- Purge verification is **fail-closed**: reachable id, intact material, missing
  tombstone, or a verification-path error all yield `fail`.
- Compaction is tenant scoped, idempotent, and retry-safe (a re-run compacts
  nothing already compacted; a failed run can complete on retry).
- Every step writes content-free audit evidence (invariant #7); the policy broker
  is never bypassed.
- Workers never run on the chat path; failures are caught, never raised
  (invariant #4).
- Claims stay honest: **no** crypto-shred, **no** guaranteed physical disk/page
  erasure, **no** pgvector reindex orchestration, **no** cross-tenant scheduler.

## Evidence
- `services/api/app/workers/deletion_compaction.py`, `workers/vector_purge.py`
- `services/api/app/workers/schemas.py` (compaction job, audit events,
  `PurgeVerification`), `workers/metrics.py` (`summarize_compaction_results`)
- `services/api/app/db/{repository,memory_repo,postgres_repo,entities}.py`
  (`list_deleted_for_compaction`, `compact_deleted_memory`, `apply_compaction`)
- `services/api/tests/test_deletion_compaction_worker.py`,
  `test_vector_purge_verification.py`
- `services/api/tests/test_deletion.py`, `test_tenant_isolation.py`
  (repo-level compaction safety)
- `scripts/pr_invariant_gate.py` (deletion-compaction / vector-purge evidence rules)

## Status: ✅ Implemented (v0.7)
