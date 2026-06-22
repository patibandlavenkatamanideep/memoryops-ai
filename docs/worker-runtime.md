# Worker Runtime + Scheduled Lifecycle Orchestration (v0.8)

> Decision record: [ADR-012](../infra/adr/ADR-012-worker-runtime-orchestration.md).
> Builds on [background-lifecycle-workers.md](background-lifecycle-workers.md)
> (the jobs) and [deletion-compaction.md](deletion-compaction.md). Deployment:
> [deployment/railway.md](deployment/railway.md).

v0.6/v0.7 gave MemoryOps the lifecycle **jobs**. v0.8 makes them **operable**: run
them on a schedule, prevent duplicate runs, retry transient faults, and record
what ran (and what failed) — without a queue or new infrastructure.

## The pieces

| Piece | File | Responsibility |
|-------|------|----------------|
| Lease / lock | `app/workers/locks.py` | TTL'd mutual exclusion per `"tenant:user"` scope |
| Retry / backoff | `app/workers/retry.py` | deterministic exponential backoff with a ceiling |
| Orchestrator | `app/workers/orchestrator.py` | lease → run jobs (retried) → record history / dead-letter → release |
| Scheduler | `app/workers/scheduler.py` | interval loop running one pass over the configured scopes |
| Worker process | `services/worker/main.py` | wires the scheduler to the real lifecycle workers |
| Health | `GET /healthz/workers` | recent runs, dead-letter/failure counts, last run per scope |

## How one scope is processed

```
acquire lease(tenant:user)                     # locks.py — duplicate runs prevented
  └─ if held by another owner → record locked_skip, do nothing
run_jobs(...) under retry/backoff              # retry.py absorbs transient store faults
  ├─ success            → record run history (completed / completed_with_findings / failed)
  └─ retries exhausted  → record dead_letter (never silently lost)
release lease                                  # always, even on failure → never deadlocked
```

A lease **expires** after `worker_lease_ttl_seconds`, so a crashed worker never
deadlocks a scope — the lease is reclaimable.

## Run history & dead-letter

Every orchestrated run appends a content-free `WorkerRunRecord` (ids/counts/status
only — never memory content): `tenant_id`, `user_id`, `status`, `jobs`, `attempts`,
scanned/changed/skipped/error counts, `owner`, `trace_id`. Statuses:

- `completed` / `completed_with_findings` / `failed` — mirror the job report;
- `locked_skip` — another replica held the lease (duplicate prevented);
- `dead_letter` — retries exhausted on a transient fault.

Stored via `worker_runs` (migration `006_worker_runtime.sql`); query with
`Repository.list_worker_runs(...)`.

## Configuration

| Setting | Default | Meaning |
|---------|---------|---------|
| `worker_interval_seconds` (`MEMORYOPS_WORKER_INTERVAL_SECONDS`) | 60 | seconds between scheduler passes |
| `worker_scopes` (`MEMORYOPS_WORKER_SCOPES`) | `tenant_demo:user_demo` | explicit `"tenant:user,…"` scopes to run |
| `worker_lease_ttl_seconds` | 300 | lease TTL (reclaimable after this) |
| `worker_max_attempts` | 3 | retry attempts per scope |
| `worker_backoff_base_seconds` | 1.0 | base backoff delay |
| `worker_backoff_factor` | 2.0 | backoff multiplier |
| `worker_backoff_max_seconds` | 30.0 | backoff ceiling |
| `worker_run_history_limit` | 500 | rows scanned for the health view |

## Running

```bash
# the worker process (interval scheduler over configured scopes)
cd services/worker && python main.py

# one pass, programmatically
from app.workers import WorkerScheduler, Scope
WorkerScheduler(repo, scopes=[Scope("t1", "u1")]).tick()

# worker health
curl localhost:8000/healthz/workers
```

## Guarantees (enforced in code + tests)

- **Duplicate runs prevented** by the lease; **never deadlocked** (leases expire).
- **Tenant scoped** — explicit scopes only; no unbounded cross-tenant scan.
- **Failures durable, not fatal** — retry → dead-letter; a bad tick never crashes
  the scheduler; one scope's failure never blocks another.
- **Content-free** run history + health.
- **Off the chat path** — maintenance only.

## Limitations (kept honest)

- Single-process interval scheduler — not a distributed cron; multiple replicas are
  safe (the lease arbitrates) but there is no central schedule coordinator.
- No external queue/broker (Celery/Temporal). The orchestrator interface is
  queue-shaped so one can be added later without touching the lifecycle workers.
- Scope enumeration is explicit (operator-configured), not auto-discovered.
