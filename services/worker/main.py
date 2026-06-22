"""Worker entrypoint (v0.8, ADR-012) — production-style scheduled lifecycle runtime.

Drives the real v0.6/v0.7 lifecycle workers (decay, archive, deletion_compaction,
deletion_verification, conflict_scan, reflection) through the orchestrator +
scheduler: leased so duplicate concurrent runs are prevented, retried with backoff,
and recorded as run history / dead-letter evidence. Replaces the legacy Phase-5
``jobs.py`` scaffold on the chat-independent maintenance path.

Configuration (via the API ``Settings``):
  * ``MEMORYOPS_WORKER_INTERVAL_SECONDS`` — seconds between passes (default 60)
  * ``MEMORYOPS_WORKER_SCOPES`` — ``"tenant:user,tenant2:user2"`` scopes to run
  * ``worker_lease_ttl_seconds`` / ``worker_max_attempts`` / backoff knobs

The API package is shared by adding ``services/api`` to ``sys.path`` (the worker
image copies it alongside; PYTHONPATH=/srv/api in the Dockerfile).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Reuse the API's repository, config, and workers without packaging the API.
_API = Path(__file__).resolve().parents[1] / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

from app.core.config import get_settings  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.db.factory import get_repository  # noqa: E402
from app.workers.scheduler import WorkerScheduler  # noqa: E402


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = get_logger("memoryops.worker")
    scheduler = WorkerScheduler(get_repository())
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
    scheduler.run_forever()


if __name__ == "__main__":
    main()
