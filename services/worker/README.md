# MemoryOps AI — Worker

Scheduled lifecycle runtime (v0.8, ADR-012). Drives the real v0.6/v0.7 lifecycle
workers — decay, archive, deletion_compaction, deletion_verification,
conflict_scan, reflection — through the orchestrator + scheduler in
`app/workers/`: leased so duplicate concurrent runs are prevented, retried with
backoff, and recorded as run history / dead-letter evidence. It shares the API's
repository (added to `PYTHONPATH`), so it works on the same in-memory or Postgres
backend.

```bash
# from services/worker, with the API venv active:
python main.py
```

Configuration (via the API `Settings`):

- `MEMORYOPS_WORKER_INTERVAL_SECONDS` — seconds between passes (default 60)
- `MEMORYOPS_WORKER_SCOPES` — `"tenant:user,tenant2:user2"` scopes to run
- `worker_lease_ttl_seconds`, `worker_max_attempts`, backoff knobs (see config)

Worker health is observable via the **API** at `GET /healthz/workers` (run
history, dead-letter / failure counts, last run per scope). See
[docs/worker-runtime.md](../../docs/worker-runtime.md).

> `jobs.py` is the legacy Phase-5 scaffold (its own ad-hoc decay/archive). It is
> superseded by the lifecycle workers + runtime on the maintenance path and kept
> only for reference.
