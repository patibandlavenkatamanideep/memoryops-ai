# Phase 12 (addendum) — Background Memory Lifecycle Workers

> Companion to [phase-12-reliability.md](phase-12-reliability.md). v0.6 extends the
> reliability/idempotency story from request-path primitives to a background
> maintenance layer. Decision record:
> [ADR-010](../../infra/adr/ADR-010-background-memory-lifecycle-workers.md).

**Question:** How is memory maintained *after* capture — decay, archive, deletion
verification, conflict scan — idempotently, safely, and without touching the chat
path?

## MemoryOps mapping
A worker layer (`services/api/app/workers/`) runs the *Update → Forget* arc of the
lifecycle off the request path. Five jobs (decay, archive, deletion verification,
conflict scan, reflection) execute against an explicit `(tenant_id, user_id)`
scope via the runner. Every job is tenant scoped, idempotent, retry-safe, audited,
and unable to resurrect deleted memory. The policy broker stays authoritative —
workers demote/archive/flag/propose only. Each run is also **traced** (v1.8,
ADR-022): the runner mints a `worker-…` correlation id and opens a `worker.job` span
per job, so a run is one correlated, content-free trace at `GET /api/traces`. See
[background-lifecycle-workers.md](../background-lifecycle-workers.md),
[memory-decay-policy.md](../memory-decay-policy.md),
[deletion-verification.md](../deletion-verification.md).

## Gate (must be true to pass)
- Workers never run on the chat request path; a worker failure is caught and
  recorded (`lifecycle_worker_failed`), never raised into a caller (invariant #4).
- Workers are tenant scoped — a run for one scope never reads/writes another's
  memory (invariant #1).
- Workers are idempotent and safe to retry — a second run makes no further change.
- Workers never modify or resurrect deleted memory; deletion verification is
  read-only and excludes deleted rows from every reachable surface (invariant #2).
- Every run and action writes audit evidence; audit metadata is content-free
  (invariant #7).
- The policy broker is never bypassed — no worker creates or promotes active
  memory.

## Evidence
- `services/api/app/workers/` (lifecycle base, decay, archive,
  deletion_verification, conflict_scan, reflection, runner, schemas, metrics)
- `services/api/tests/test_lifecycle_worker.py` (runner, audit, failure-isolation,
  tenant scoping, content-free results)
- `services/api/tests/test_decay_worker.py`, `test_archive_worker.py`,
  `test_deletion_verification_worker.py`, `test_conflict_scan_worker.py`
- `services/api/tests/test_worker_idempotency.py` (idempotency / retry safety)
- `scripts/pr_invariant_gate.py` (worker evidence rules)

## Status: ✅ Implemented (v0.6)
