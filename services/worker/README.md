# MemoryOps AI — Worker

Background intelligence (Phase 5 scaffold): decay, archival, conflict detection,
and reflection/compression. Jobs run against the same repository interface as the
API, so they can later move to Celery/Temporal with retries + DLQs.

```bash
# from services/worker, with the API venv active:
python main.py          # interval loop (WORKER_INTERVAL_SECONDS, default 60)
```

In Docker Compose the worker shares the Postgres backend with the API.
