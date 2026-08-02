"""Worker entrypoint (ADR-012) — production-style scheduled lifecycle runtime.

Drives the real lifecycle workers (decay, archive, retention, deletion_compaction,
deletion_verification, conflict_scan, reflection) through the orchestrator +
scheduler: leased with a renewing heartbeat, retried per job with backoff,
dead-lettered when a job's retry budget is exhausted, and recorded as run history.

Packaging
---------
This module imports ``app.*`` as an ordinary installed dependency. It previously
mutated ``sys.path`` at import time to point at ``services/api``, which tied the
worker to the repository layout, made imports order-dependent, and blocked shipping
it as a wheel. ``memoryops-api`` is now a properly built distribution, so the worker
just depends on it and starts as::

    memoryops-worker          # console script (pip install -e services/worker)
    python main.py            # equivalent, from this directory

Configuration (via the API ``Settings``):
  * ``MEMORYOPS_WORKER_INTERVAL_SECONDS`` — seconds between passes (default 60)
  * ``MEMORYOPS_WORKER_SCOPES`` — ``"tenant:user,tenant2:user2"`` scopes to run
  * ``worker_lease_ttl_seconds`` / ``worker_max_attempts`` / backoff knobs

Shutdown
--------
SIGTERM/SIGINT set a cooperative stop flag. The worker finishes the scope it is in,
releases its lease, and exits 0 — so a deploy no longer hard-kills a mid-write scope
and leaves it locked for the remainder of the lease TTL.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.factory import get_repository
from app.workers.scheduler import WorkerScheduler
from app.workers.shutdown import ShutdownSignal


def main() -> int:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = get_logger("memoryops.worker")

    # Install handlers before the first tick so a SIGTERM during startup is honoured.
    with ShutdownSignal() as shutdown:
        scheduler = WorkerScheduler(get_repository(), shutdown=shutdown)
        logger.info(
            "worker runtime starting",
            extra={
                "event": "worker_start",
                "status": "ok",
                "interval_s": settings.worker_interval_seconds,
                "scopes": len(scheduler.scopes),
                "storage": settings.storage,
            },
        )
        ticks = scheduler.run_forever()
        logger.info(
            "worker runtime stopped",
            extra={
                "event": "worker_stop",
                "status": "ok",
                "ticks": ticks,
                "signal": shutdown.signal_name,
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
