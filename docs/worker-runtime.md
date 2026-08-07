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
| `operational_database_url` (`OPERATIONAL_DATABASE_URL`) | *(unset)* | separately authorized cross-tenant connection for global worker health |

> **Global worker health & tenant isolation (v2.3, ADR-027).** `GET /healthz/workers`
> aggregates runs across *all* tenants, so it must not use the request-scoped,
> RLS-enforced connection (that one is — correctly — tenant-scoped and rejects an
> unscoped query). It reads instead through an explicit operational path
> (`list_worker_runs_operational`) backed by `OPERATIONAL_DATABASE_URL`, a
> monitoring/BYPASSRLS role. Leave it unset and worker health fails **closed**:
> `{ healthy: null, detail: "operational access not configured", … }` — never a crash,
> never a tenant-boundary relaxation.

## Running

```bash
# install the API + worker as distributions (no PYTHONPATH, no sys.path)
pip install ./services/api ./services/worker

# the worker process (interval scheduler over configured scopes)
memoryops-worker

# one pass, programmatically
from app.workers import WorkerScheduler, Scope
WorkerScheduler(repo, scopes=[Scope("t1", "u1")]).tick()

# worker health
curl localhost:8000/healthz/workers
```

The worker previously mutated `sys.path` at import time to reach `services/api`,
which tied it to the repository layout and blocked shipping it as a wheel. It now
declares an ordinary dependency on the `memoryops-api` distribution and exposes a
`memoryops-worker` console script.

## Lease heartbeat (long-running scopes)

`WorkerLeaseManager.renew()` existed from v0.8 but nothing called it: the
orchestrator acquired a lease once and ran the whole scope. Any scope whose jobs
outlived `worker_lease_ttl_seconds` (default 300s) silently lost exclusivity
mid-run, and a second replica could acquire the same tenant/user and mutate it
concurrently. Idempotency limits the damage; it does not make it correct.

`app/workers/heartbeat.py` renews the lease on a background thread at `ttl/3`, and
**fails closed** if renewal ever fails: the scope stops between jobs, remaining jobs
are recorded as `aborted`, and the run is recorded as `lease_lost`.

> **Residual risk, stated plainly.** This is cooperative, not fencing. The abort flag
> is observed *between* jobs, so a worker that stalls (long GC pause, VM freeze)
> after its check and resumes past expiry can still finish the write it was in.
> Closing that needs a monotonic fence token checked at the storage write itself —
> a schema change plus threading the fence through every job's writes. Tracked as
> follow-up. What is closed now is the common, previously *guaranteed* case: a job
> that simply takes longer than the TTL.

## Retry granularity

Retry used to wrap `run_jobs` as a whole. But lifecycle workers catch their own
errors and **return** `status=failed` rather than raising, so the wrapper only ever
saw clean returns — a failing job was recorded as failed and then dropped: never
retried, never dead-lettered.

Retry is now per job, keyed off the returned status:

| Job status | Retried? | Why |
| --- | --- | --- |
| `failed` | yes, to `worker_max_attempts` | transient fault |
| `dead_letter` | terminal | budget exhausted; replayable, not lost |
| `completed_with_findings` | **no** | a finding is a real result, not a fault; retrying would multiply audit events and mask it |
| `skipped` / `completed` | no | nothing to retry |
| `aborted` | no | lease lost or shutdown; deliberately not started |

## Graceful shutdown

`run_forever` looped on a bare `time.sleep` with no signal handling, so every deploy
hard-killed the worker mid-tick and left its lease held for the rest of the TTL —
and with a 60s interval the process spent nearly all its life unable to react to
SIGTERM at all.

SIGTERM/SIGINT now set a cooperative stop flag (`app/workers/shutdown.py`). The
inter-tick wait is an interruptible `Event.wait`, so the signal is acted on
immediately: the scope in flight finishes, its lease is released, remaining scopes
are left for the next replica, and the process exits 0. Verified end to end in the
`worker` CI job.

## Guarantees (enforced in code + tests)

- **Normal TTL overlap prevented** — heartbeat-renewed cooperative leases keep a
  scope exclusive even when its jobs outlive the original TTL; **never deadlocked**
  (leases expire). This is *not* a guarantee against a paused-then-resumed process:
  database-enforced fencing remains future work (see the residual risk above).
- **Lease loss fails closed** — no further mutation once ownership is unprovable,
  checked between jobs.
- **Tenant scoped** — explicit scopes only; no unbounded cross-tenant scan.
- **Failures durable, not fatal** — per-job retry → dead-letter; a bad tick never
  crashes the scheduler; one scope's failure never blocks another.
- **Clean termination** — SIGTERM finishes the current scope, releases the lease,
  exits 0.
- **Content-free** run history + health.
- **Off the chat path** — maintenance only.

## Limitations (kept honest)

- Single-process interval scheduler — not a distributed cron; multiple replicas are
  safe (the lease arbitrates) but there is no central schedule coordinator.
- Lease protection is cooperative, not fenced (see the residual risk above).
- No external queue/broker (Celery/Temporal). The orchestrator interface is
  queue-shaped so one can be added later without touching the lifecycle workers.
- Scope enumeration is explicit (operator-configured), not auto-discovered — a
  dynamic scope registry is separate follow-up work.
- Dead-lettered jobs are recorded and queryable, but there is no one-command
  **replay** yet; re-running the scope re-attempts the work.

## The worker imports the API, it does not reach for it (v2.4)

`services/worker/jobs.py` — the superseded Phase-5 scaffold, kept for reference —
inserted `../api` into `sys.path` at import time so it could reach the API package
without depending on it:

```python
_API = Path(__file__).resolve().parents[1] / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))
```

Meanwhile `services/worker/pyproject.toml` stated that the practice had been removed
and that "there is no PYTHONPATH or `sys.path.insert()` left in a production
entrypoint". The file ships in the worker image, so the claim was false wherever it
was read.

A service that rewrites its own import path at startup can resolve a **different
dependency set** than the service it is importing from, and the failure surfaces as
version skew nobody can trace back to its cause. The worker already declares the API
as an ordinary dependency, so the mutation was also unnecessary — the imports resolve
without it.

Removed, and now enforced structurally: `scripts/repo_trust_guards.py` rejects any
`sys.path` mutation in shipped service code, AST-based so the comments explaining this
history do not trip it. See
[security/repository-trust-guards.md](security/repository-trust-guards.md).
