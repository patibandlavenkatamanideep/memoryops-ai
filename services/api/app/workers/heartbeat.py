"""Lease heartbeat for long-running worker scopes (ADR-012 follow-up).

The problem this closes
-----------------------
``WorkerLeaseManager.renew()`` existed from v0.8 but nothing ever called it. The
orchestrator acquired a lease once, ran the whole scope, and released it. A lease
has a TTL (``worker_lease_ttl_seconds``, default 300s), so any scope whose jobs
took longer than the TTL silently lost its exclusivity mid-run:

    t=0    worker A acquires lease for tenant:user (expires t=300)
    t=300  lease expires while A is still compacting
    t=301  worker B acquires the *same* scope and starts mutating it
    t=420  A finishes, and releases a lease it no longer owns

Idempotent jobs reduce the damage but do not make concurrent lifecycle mutation of
one scope correct — decay, retention, and compaction all write.

The fix is two-sided:

  * **Renew** the lease on a background thread at ``ttl/3`` so a healthy long job
    keeps its exclusivity indefinitely.
  * **Fail closed** when renewal fails. Losing the lease means another replica may
    now own the scope, so the heartbeat sets ``lost``; the orchestrator checks it
    between jobs and stops before any further mutation.

Residual risk (deliberately documented, not hidden)
---------------------------------------------------
This is cooperative, not fencing. The abort flag is only observed *between* jobs,
so a worker that stalls (long GC pause, VM freeze) after its check and resumes
after the lease expired can still complete the write it was in the middle of. True
protection needs a monotonic fence token checked at the storage write itself —
that requires threading a fence through every job's writes and a schema change,
and is tracked as follow-up. What this closes is the common, previously guaranteed
case: a job that simply *takes longer than the TTL*.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from ..core.logging import get_logger
from .locks import WorkerLeaseManager

logger = get_logger("memoryops.workers.heartbeat")

# Renew at a third of the TTL: two consecutive renewals may fail before the lease
# actually expires, so a transient store blip does not needlessly abort a run.
_RENEW_FRACTION = 3.0


class LeaseHeartbeat:
    """Renews a held lease on a daemon thread; flags loss so callers fail closed.

    Used as a context manager around a scope's work::

        with LeaseHeartbeat(leases, key, ttl_seconds=300) as hb:
            run_jobs(..., should_abort=hb.lost.is_set)
            if hb.lost.is_set():
                ...  # fail closed
    """

    def __init__(
        self,
        leases: WorkerLeaseManager,
        key: str,
        *,
        ttl_seconds: int,
        interval_seconds: float | None = None,
        renew: Callable[[], bool] | None = None,
    ) -> None:
        self._leases = leases
        self._key = key
        self._interval = interval_seconds or max(ttl_seconds / _RENEW_FRACTION, 1.0)
        self._renew = renew or (lambda: self._leases.renew(self._key))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Set when the lease could no longer be renewed — the scope is no longer ours.
        self.lost = threading.Event()
        self.renewals = 0

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> LeaseHeartbeat:
        self._thread = threading.Thread(
            target=self._loop, name=f"lease-heartbeat:{self._key}", daemon=True
        )
        self._thread.start()
        return self

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def __enter__(self) -> LeaseHeartbeat:
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    # ── internals ────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        # `wait` returns True when stopped — an interruptible sleep, so shutdown is
        # immediate rather than waiting out a full interval.
        while not self._stop.wait(self._interval):
            try:
                renewed = self._renew()
            except Exception as exc:  # noqa: BLE001 — a raising store means we can't prove ownership
                renewed = False
                logger.warning(
                    "lease renewal raised; treating the lease as lost",
                    extra={
                        "event": "worker_lease_renew_error",
                        "status": "failed",
                        "error": type(exc).__name__,
                    },
                )
            if renewed:
                self.renewals += 1
                continue
            # Fail closed: we can no longer prove we own this scope.
            self.lost.set()
            logger.warning(
                "worker lease lost; aborting scope before further mutation",
                extra={
                    "event": "worker_lease_lost",
                    "status": "failed",
                    "renewals": self.renewals,
                },
            )
            return
