"""Graceful shutdown for the worker process (ADR-012 follow-up).

Before this, ``WorkerScheduler.run_forever`` looped on a bare ``time.sleep`` with no
signal handling at all. On Railway (or any orchestrator) a deploy sends SIGTERM and
then SIGKILLs after a grace period, so the worker was always hard-killed:

  * mid-tick work was cut off wherever it happened to be;
  * the held lease was never released, so that scope stayed locked for the rest of
    its TTL and the next replica skipped it;
  * the sleep was uninterruptible, so a worker with a 60s interval spent most of
    its life in a state where SIGTERM did nothing until the kill landed.

``ShutdownSignal`` makes the stop cooperative: signals set an event, the scheduler
waits on that event instead of sleeping (so it wakes immediately), finishes the tick
it is in, releases its lease, and exits 0.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType

from ..core.logging import get_logger

logger = get_logger("memoryops.workers.shutdown")

# The signals an orchestrator uses to ask a process to stop.
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


class ShutdownSignal:
    """A stop flag fed by SIGTERM/SIGINT, usable as an interruptible sleep.

    Signal handlers can only be installed from the main thread of the main
    interpreter; ``install()`` degrades to a no-op elsewhere (tests, embedded use)
    rather than raising, and the event can still be set programmatically.
    """

    def __init__(self) -> None:
        self._event = threading.Event()
        self._previous: dict[int, object] = {}
        self.signal_name: str | None = None

    # ── flag ─────────────────────────────────────────────────────────────────
    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        self._event.set()

    def wait(self, timeout: float | None = None) -> bool:
        """Sleep up to ``timeout``, returning True as soon as a stop is requested.

        This replaces ``time.sleep`` in the scheduler loop so a SIGTERM arriving
        mid-interval is acted on immediately instead of after the full interval.
        """
        return self._event.wait(timeout)

    # ── installation ─────────────────────────────────────────────────────────
    def install(self) -> ShutdownSignal:
        for sig in _STOP_SIGNALS:
            try:
                self._previous[sig] = signal.getsignal(sig)
                signal.signal(sig, self._handle)
            except (ValueError, OSError):  # not the main thread / unsupported
                logger.debug(
                    "could not install signal handler",
                    extra={"event": "worker_signal_install_skipped", "signal": sig},
                )
        return self

    def restore(self) -> None:
        for sig, handler in self._previous.items():
            try:
                signal.signal(sig, handler)  # type: ignore[arg-type]
            except (ValueError, OSError, TypeError):
                pass
        self._previous.clear()

    def __enter__(self) -> ShutdownSignal:
        return self.install()

    def __exit__(self, *exc_info) -> None:
        self.restore()

    # ── handler ──────────────────────────────────────────────────────────────
    def _handle(self, signum: int, _frame: FrameType | None) -> None:
        self.signal_name = signal.Signals(signum).name
        # Deliberately not exiting here: the scheduler must finish its current tick
        # and release its lease. A second signal still hard-kills via the default
        # handler only if the operator sends one after we restore handlers.
        logger.info(
            "shutdown requested; finishing current tick",
            extra={
                "event": "worker_shutdown_requested",
                "status": "ok",
                "signal": self.signal_name,
            },
        )
        self._event.set()
