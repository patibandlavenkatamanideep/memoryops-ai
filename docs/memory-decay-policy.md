# Memory Decay & Archive Policy (v0.6)

> Part of the [background lifecycle workers](background-lifecycle-workers.md).
> Decision record: [ADR-010](../infra/adr/ADR-010-background-memory-lifecycle-workers.md).

Decay and archive are how MemoryOps lets memory **age gracefully** instead of
accumulating forever. Both are reversible and governed — neither deletes data.

## Decay policy

The decay worker demotes memory in ranking by lowering its `importance`; it does
**not** delete or archive.

**Eligibility** (an active, non-deleted memory):

- `age_days >= workers_decay_age_days` (default 90), **or**
- `confidence < workers_decay_min_confidence` (default 0.3),

**and** `importance > workers_decay_importance_floor` (there is something to
reduce).

**Action:** `importance := max(floor, importance - workers_decay_importance_step)`
(default step 2, floor 1). The memory is stamped `metadata.lifecycle.decayed =
true` with `decay_age_days` and `decay_from_importance`, and a
`memory_decay_applied` audit event is recorded (old/new importance, age, whether
low-confidence triggered it).

**Idempotency:** a decayed memory is skipped on subsequent runs (the `decayed`
marker), so decay applies **once** per memory and re-runs converge. This is the
deliberate v0.6 trade-off: simple, provably idempotent, and easy to audit.
Progressive multi-round decay (clearing the marker on a schedule) is future work.

**Safety:** deleted memory is never selected (the scan reads active rows only),
so decay never touches or resurrects it.

## Archive policy

The archive worker moves stale memory out of active retrieval by setting
`status = archived` (still stored, recoverable via the control plane, excluded
from retrieval).

**Eligibility** (an active, non-deleted memory):

- not pinned/protected — `metadata.pinned` and `metadata.protected` are both
  falsy;
- `age_days >= workers_archive_age_days` (default 180);
- not recently used — `now - last_used < workers_archive_recent_use_days`
  (default 30), where `last_used` is `metadata.lifecycle.last_used_at` if present,
  otherwise `created_at`.

> **Why not `updated_at`?** Decay (and other maintenance) bumps `updated_at`.
> Using it for "recently used" would let a decay pass make a memory look freshly
> used and block archival. Archive reads an explicit `last_used_at` signal
> instead (set by retrieval/reinforcement in a future milestone), falling back to
> `created_at`.

**Action:** `status := archived`, `archived_at := now`, stamp
`metadata.lifecycle.archived_by_worker = true`, and record a
`memory_archived_by_worker` audit event. In `--dry-run`, the worker instead emits
`memory_archive_candidate` and changes nothing.

**Idempotency:** an archived row leaves the active set, so re-runs neither
re-archive nor double-count it.

## Relationship to deletion

Decay and archive are **not** forgetting. Forgetting (soft delete) is a separate,
explicit governance action; its durability over time is checked by the
[deletion verification worker](deletion-verification.md). The policy broker
remains authoritative over what becomes/stays active memory — workers only demote,
archive, or flag.
