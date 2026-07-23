# ADR-012 — Worker Runtime + Scheduled Lifecycle Orchestration

- Status: Accepted (v0.8)
- Date: 2026-06-22
- Supersedes: none
- Related: ADR-001 (storage), ADR-004 (observability), ADR-010 (background
  lifecycle workers), ADR-011 (deletion compaction)

## Context

v0.6 and v0.7 gave MemoryOps real lifecycle workers (decay, archive, conflict
scan, reflection, deletion compaction, deletion verification) and a tenant-scoped
`runner`. But they were still *callable functions*: something external had to
decide when to run them, nothing prevented two replicas from running the same
scope at once, a transient store fault just failed the run, and there was no
durable record of what ran or what failed. That is library code, not operable
infrastructure.

The product brief's `services/worker` was still the Phase-5 scaffold (`jobs.py`)
with its own ad-hoc decay/archive logic, disconnected from the v0.6/v0.7
lifecycle workers.

## Decision

Add a production-style **worker runtime** in `services/api/app/workers/` and point
the `services/worker` process at it. Four small, composable pieces:

1. **Lease/lock** (`locks.py` + `Repository.try_acquire_lease`) — a TTL'd
   mutual-exclusion token keyed by `"tenant:user"`. Only the holder processes a
   scope; a second worker that fails to acquire skips it. Leases expire, so a
   crashed worker never deadlocks a scope. Atomicity lives in the repository
   (in-memory live-owner check; Postgres `INSERT … ON CONFLICT … WHERE expired/own`).
2. **Retry/backoff** (`retry.py`) — deterministic exponential backoff with a
   ceiling, wrapping the per-scope work to absorb transient faults. Exhausted
   retries are dead-lettered, never silently lost.
3. **Orchestrator** (`orchestrator.py`) — for each explicit scope: acquire lease
   → `run_jobs` under retry → persist a content-free **run-history** record (or a
   **dead-letter** record) → always release the lease. One scope failing never
   blocks another.
4. **Scheduler** (`scheduler.py`) — a thin interval loop that runs one
   orchestration pass per tick over the configured scopes; `max_ticks` /
   `run_once` make it testable and scriptable.

Run history + leases are persisted via additive repository methods and a new
migration (`006_worker_runtime.sql`: `worker_leases`, `worker_runs`). A
`GET /healthz/workers` endpoint surfaces recent runs, dead-letter / failure
counts, and the last run per scope.

### Design constraints

- **Tenant isolation preserved.** Scope enumeration stays explicit — the
  scheduler is handed `"tenant:user"` scopes (`worker_scopes`); there is no
  unbounded cross-tenant scan (consistent with ADR-010).
- **Duplicate runs prevented** by the lease; **never deadlocked** because leases
  expire.
- **Failures are durable, not fatal.** Transient faults retry; exhausted retries
  dead-letter; a bad tick never crashes the scheduler.
- **Content-free.** Run records and health carry ids/counts/status only — never
  memory content (invariant #7 spirit; aligns with worker audit metadata).
- **Off the chat path.** Unchanged from ADR-010 — the runtime is maintenance only.

## Alternatives considered

- **Celery / Temporal / a real queue.** Rejected for v0.8: adds infra and a
  broker dependency for a single-scope, low-frequency maintenance workload. The
  lease + retry + dead-letter primitives cover the need and keep the repository as
  the only backing store. The orchestrator interface is queue-shaped, so this can
  be swapped later without touching the lifecycle workers.
- **Advisory `pg_advisory_lock`.** Rejected: ties locking to a live DB session and
  is invisible/untestable for the in-memory backend. A lease row works on both
  backends and is inspectable (`/healthz/workers`, `get_lease`).
- **Cross-tenant scope auto-discovery.** Deferred (as in ADR-010): scope
  enumeration stays explicit to keep isolation structural.

## Consequences

- `services/worker/main.py` now drives the real lifecycle workers via the
  scheduler; the legacy `jobs.py` scaffold is superseded on the maintenance path.
- New operable surface: leased runs, retry/backoff, durable run history,
  dead-letter records, and a worker health endpoint.
- New migration `006_worker_runtime.sql`; additive repository methods only.
- Future work (v0.9+): governed retention/legal-hold inputs to the workers;
  optional queue/cron backend behind the same orchestrator interface; per-scope
  scheduling cadence.

## Amendment (v2.3, ADR-027): global worker health respects tenant isolation

`summarize_runtime_health` (the data behind `/healthz/workers`) is a *global* operator
view that aggregates runs across every tenant. It therefore must **not** use the
request-scoped, RLS-enforced connection — that one is correctly tenant-scoped and rejects
an unscoped `list_worker_runs()` query (which is why worker health had regressed to
"unavailable"). Health now reads through an explicit
`Repository.list_worker_runs_operational()` backed by a separately authorized
`OPERATIONAL_DATABASE_URL` (a monitoring/BYPASSRLS role); unconfigured, it fails **closed**
to a documented "operational access not configured" state. Orchestration, leasing, retry,
and scheduling semantics are unchanged. See ADR-027 and `docs/worker-runtime.md`.
