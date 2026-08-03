"""Scheduler loop for the worker runtime (v0.8, ADR-012).

A deliberately thin interval scheduler: every ``interval_seconds`` it runs one
orchestration pass (`WorkerOrchestrator.run_once`) over the configured scopes. The
heavy lifting — leasing, retries, run history, dead-letter — lives in the
orchestrator; this just paces it. Production-grade scheduling (cron/queue) can
replace the loop without touching the orchestrator. ``max_ticks`` makes the loop
testable; ``run_once`` makes a single pass scriptable.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from ..core.config import get_settings
from ..core.logging import get_logger
from ..db.entities import WorkerRunRecord
from ..db.repository import Repository
from .orchestrator import Scope, WorkerOrchestrator, parse_scopes
from .shutdown import ShutdownSignal

logger = get_logger("memoryops.workers.scheduler")


class WorkerScheduler:
    def __init__(
        self,
        repo: Repository,
        *,
        scopes: list[Scope] | None = None,
        interval_seconds: int | None = None,
        orchestrator: WorkerOrchestrator | None = None,
        sleep: Callable[[float], None] = time.sleep,
        shutdown: ShutdownSignal | None = None,
    ) -> None:
        s = get_settings()
        self._repo = repo
        self._scopes = scopes if scopes is not None else parse_scopes(s.worker_scopes)
        self._interval = interval_seconds or s.worker_interval_seconds
        # The orchestrator needs the same stop flag so it can break between scopes
        # and between jobs, not just between ticks.
        self._shutdown = shutdown
        self._orchestrator = orchestrator or WorkerOrchestrator(repo, shutdown=shutdown)
        self._sleep = sleep

    @property
    def scopes(self) -> list[Scope]:
        return self._scopes

    def tick(self, *, trace_id: str | None = None) -> list[WorkerRunRecord]:
        trace_id = trace_id or f"worker-{uuid.uuid4().hex[:12]}"
        records = self._orchestrator.run_once(self._scopes, trace_id=trace_id)
        logger.info(
            "worker scheduler tick",
            extra={
                "event": "worker_tick",
                "status": "done",
                "scopes": len(self._scopes),
                "runs": len(records),
            },
        )
        return records

    def run_forever(self, *, max_ticks: int | None = None) -> int:
        """Loop ``tick`` every interval. ``max_ticks`` bounds it for tests.

        A tick never raises into the loop: the orchestrator records per-scope
        failures, and any unexpected error is caught here so the scheduler keeps
        running (the worker process must not crash on a single bad pass).

        Shutdown is cooperative. When a ``ShutdownSignal`` is supplied the
        between-tick wait is an interruptible ``Event.wait`` rather than
        ``time.sleep``, so a SIGTERM arriving mid-interval is acted on immediately
        instead of after the full interval (with a 60s default, the process
        previously spent nearly all its life ignoring SIGTERM until the SIGKILL).
        """
        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            if self._stop_requested():
                break
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 — scheduler must survive a bad tick
                logger.warning(
                    "worker scheduler tick failed",
                    extra={"event": "worker_tick_error", "status": "failed",
                           "error": type(exc).__name__},
                )
            ticks += 1
            if self._stop_requested():
                break
            if max_ticks is None or ticks < max_ticks:
                self._wait(self._interval)
        if self._stop_requested():
            logger.info(
                "worker scheduler stopped cleanly",
                extra={"event": "worker_stopped", "status": "ok", "ticks": ticks},
            )
        return ticks

    # ── shutdown plumbing ─────────────────────────────────────────────────────
    def _stop_requested(self) -> bool:
        return self._shutdown is not None and self._shutdown.is_set()

    def _wait(self, seconds: float) -> None:
        """Interruptible inter-tick wait; falls back to the injected sleep."""
        if self._shutdown is not None:
            self._shutdown.wait(seconds)
        else:
            self._sleep(seconds)
