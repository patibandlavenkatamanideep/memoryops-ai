# Background Memory Lifecycle Workers (v0.6)

> Authoritative decision record: [ADR-010](../infra/adr/ADR-010-background-memory-lifecycle-workers.md).
> Related: [memory-decay-policy.md](memory-decay-policy.md),
> [deletion-verification.md](deletion-verification.md),
> [governance.md](governance.md), [security.md](security.md).

The worker layer maintains memory **after** it is captured — the *Update → Forget*
arc of the lifecycle. It runs **outside the chat request path** and never blocks a
response. Code lives in `services/api/app/workers/`.

## Why a worker layer

Through v0.5, nothing maintained memory once written: stale memory kept its
importance forever, nothing re-checked the deletion guarantee over time, and
conflicts were only detected for a single new candidate at write time. Workers
close that gap without weakening any invariant.

## The jobs

| Job | What it does | Mutates? | Default |
|-----|--------------|----------|---------|
| `decay` | Reduce importance of old / low-confidence active memory toward a floor | yes (importance) | on |
| `archive` | Set stale, not-recently-used, non-pinned memory to `archived` | yes (status) | on |
| `conflict_scan` | Flag contradicting memories as review candidates (advisory) | no | on |
| `reflection` | Propose consolidation of low-importance clusters | no | **off** |
| `deletion_verification` | Confirm deleted memory is unreachable; record evidence | no | on |

`all` runs them in a deliberate order: mutating jobs first, then `reflection`,
then read-only `deletion_verification` last so it observes the final state.

## Operating principles (enforced in code + tests)

- **Tenant scoped.** A worker only touches the `(tenant_id, user_id)` it is
  given, via the repository's scoped methods (invariant #1). It cannot reach
  another tenant's memory.
- **Idempotent + safe to retry.** Markers under `metadata.lifecycle.*` make a
  re-run a no-op for already-processed rows. Decay never double-decays; archive
  never re-archives.
- **Never resurrects deleted memory.** Mutating workers read active rows only and
  re-filter `status != deleted`; deletion verification is read-only (invariant #2).
- **Policy broker stays authoritative.** Workers demote / archive / flag /
  propose. They never bypass policy to create or promote active memory.
- **Audited.** Every run emits `lifecycle_worker_started/completed/failed`; every
  action emits a typed event. Audit metadata is content-free — ids, counts, and
  flags only, never raw memory content or user messages (invariant #7).
- **Never blocks chat.** Workers are off the request path; a worker exception is
  caught, recorded as `lifecycle_worker_failed`, and returned as a failed result
  (invariant #4).

## Structured results

`run_jobs(...)` returns a `WorkerRunReport` aggregating one `WorkerJobResult` per
job. Each result carries: `job`, `tenant_id`, `user_id`, `started_at`,
`completed_at`, `status`, `scanned_count`, `changed_count`, `skipped_count`,
`error_count`, `audit_event_ids`, and content-free `details`. `report.ok` is
`False` if any job failed or a verification finding surfaced.
`workers/metrics.py::summarize_worker_results` rolls these up for a metrics view.

Statuses: `completed`, `completed_with_findings` (e.g. a deletion leak),
`skipped` (job disabled / not applicable), `failed` (caught error).

## Running locally

```bash
cd services/api
# all jobs for one tenant/user scope
MEMORYOPS_STORAGE=memory .venv/bin/python -m app.workers.runner --tenant t1 --user u1 --job all
# specific jobs, repeatable flag
.venv/bin/python -m app.workers.runner --tenant t1 --user u1 --job decay --job archive
# dry run: report candidates, change nothing
.venv/bin/python -m app.workers.runner --tenant t1 --user u1 --job archive --dry-run
```

The CLI prints the JSON report and exits non-zero if `report.ok` is `False`, so it
doubles as a scheduled health check.

Programmatic use:

```python
from app.workers import run_jobs
report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["all"])
```

## Configuration

Thresholds are `Settings.workers_*` (see `app/core/config.py`):

| Setting | Default | Meaning |
|---------|---------|---------|
| `workers_decay_age_days` | 90 | age that makes a memory decay-eligible |
| `workers_decay_min_confidence` | 0.3 | below this, decay-eligible regardless of age |
| `workers_decay_importance_floor` | 1 | decay never reduces below this |
| `workers_decay_importance_step` | 2 | importance reduction per decay |
| `workers_archive_age_days` | 180 | age that makes a memory archive-eligible |
| `workers_archive_recent_use_days` | 30 | "recently used" window that blocks archive |
| `workers_conflict_scan_max_memories` | 200 | cap on memories scanned per run |
| `workers_reflection_enabled` | `false` | enable reflection proposals |
| `workers_reflection_min_cluster_size` | 5 | min cluster to propose consolidation |
| `workers_reflection_max_importance` | 3 | only cluster memory at/below this importance |

`MEMORYOPS_WORKERS_REFLECTION=1` is the public toggle for reflection.

## How this fits the Railway worker service

Deployment is Railway-only (one project, five services: web/api/worker + Postgres
+ Redis — see [deployment/railway.md](deployment/railway.md)). The `worker`
service is the natural host for a scheduled loop that, for each active tenant/user
scope, calls `run_jobs(...)`. **Scope enumeration and scheduling live in the
orchestrator**, not in the workers — workers are deliberately single-scope so
tenant isolation is structural. No new infrastructure or live deployment is
introduced by v0.6.

## Limitations / future work

- Reflection is proposal-only; a governed write path (landing as `pending`) is
  deferred.
- Cross-tenant scope enumeration is the orchestrator's responsibility; there is
  no repository method that lists all scopes yet.
- Deletion verification covers **logical** forgetting only; physical vector
  compaction / crypto-shred is staged — see
  [deletion-verification.md](deletion-verification.md).
