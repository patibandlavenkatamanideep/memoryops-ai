# Phase 14 (addendum) — Worker Runtime + Scheduled Lifecycle Orchestration

> Companion to [phase-12-background-lifecycle-workers.md](phase-12-background-lifecycle-workers.md),
> [phase-12-reliability.md](phase-12-reliability.md), and
> [phase-13-infrastructure.md](phase-13-infrastructure.md). v0.8 turns the
> lifecycle workers from callable functions into an operable runtime. Decision
> record: [ADR-012](../../infra/adr/ADR-012-worker-runtime-orchestration.md).

**Question:** How are the v0.6/v0.7 lifecycle jobs *operated* — scheduled, run
without duplication across replicas, retried on transient faults, and recorded
(including failures) — without adding queue infrastructure?

## MemoryOps mapping
A worker runtime in `services/api/app/workers/` composed of a lease/lock
(`locks.py`), a retry/backoff policy (`retry.py`), an orchestrator
(`orchestrator.py`), and a thin scheduler (`scheduler.py`). For each explicit
`(tenant, user)` scope it acquires a lease, runs the lifecycle jobs under retry,
persists a content-free run-history record (or a dead-letter record on exhausted
retries), and always releases the lease. Leases + run history persist via
`006_worker_runtime.sql`; `GET /healthz/workers` surfaces health. `services/worker/
main.py` drives the real lifecycle workers (superseding the legacy `jobs.py`).
See [worker-runtime.md](../worker-runtime.md).

## Gate (must be true to pass)
- Duplicate concurrent runs of a scope are prevented by a lease; an expired lease
  is reclaimable so a crashed worker never deadlocks a scope.
- A retry/backoff policy absorbs transient faults; exhausted retries become a
  dead-letter record — never silently lost.
- Run history + dead-letter records are persisted and queryable; worker health is
  visible via an endpoint.
- Scopes are explicit (no unbounded cross-tenant scan); run records are tenant
  scoped and content-free.
- One scope's failure never blocks another; a bad scheduler tick never crashes the
  worker process; the runtime stays off the chat path.

## Evidence
- `services/api/app/workers/{locks,retry,orchestrator,scheduler}.py`
- `services/api/app/db/{repository,memory_repo,postgres_repo,entities}.py`
  (`try_acquire_lease`/`renew_lease`/`release_lease`/`get_lease`,
  `add_worker_run`/`list_worker_runs`, `WorkerLease`/`WorkerRunRecord`)
- `infra/db/migrations/006_worker_runtime.sql`,
  `services/api/app/models/sqlalchemy_models.py` (`WorkerLeaseORM`/`WorkerRunORM`)
- `services/api/app/routes/health.py` (`GET /healthz/workers`)
- `services/worker/main.py` (scheduler entrypoint)
- `services/api/tests/test_worker_retry.py`, `test_worker_locks.py`,
  `test_worker_orchestrator.py`, `test_worker_health.py`,
  `test_tenant_isolation.py`, `test_deletion.py`
- `scripts/pr_invariant_gate.py` (worker-runtime evidence rules)

## Status: ✅ Implemented (v0.8)
