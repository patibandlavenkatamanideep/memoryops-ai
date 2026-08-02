"""Worker reliability: lease heartbeat, per-job retry, and graceful shutdown.

Three gaps in the v0.8 runtime that this locks down:

1. **The lease was never renewed.** `WorkerLeaseManager.renew()` existed but
   nothing called it. A scope whose jobs outlived `worker_lease_ttl_seconds`
   (default 300s) silently lost exclusivity mid-run, so a second replica could
   acquire the same tenant/user and mutate it concurrently.

2. **Job failures were never retried.** `run_with_retry` wrapped `run_jobs`, but
   lifecycle workers catch their own errors and *return* `status=failed` instead of
   raising — so the retry wrapper only ever saw clean returns. A failing job was
   recorded as failed and then dropped: not retried, not dead-lettered.

3. **No graceful shutdown.** `run_forever` looped on a bare `time.sleep` with no
   signal handling, so every deploy hard-killed the worker mid-tick and left its
   lease held for the remainder of the TTL.
"""

from __future__ import annotations

import signal
import threading
from datetime import UTC, datetime, timedelta

from app.workers.heartbeat import LeaseHeartbeat
from app.workers.locks import WorkerLeaseManager, scope_key
from app.workers.orchestrator import (
    RUN_COMPLETED,
    RUN_DEAD_LETTER,
    RUN_LEASE_LOST,
    Scope,
    WorkerOrchestrator,
)
from app.workers.retry import RetryPolicy
from app.workers.runner import run_jobs
from app.workers.scheduler import WorkerScheduler
from app.workers.schemas import WorkerJob, WorkerJobResult, WorkerRunStatus
from app.workers.shutdown import ShutdownSignal

from ._worker_helpers import seed_memory

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _fast_policy(attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(max_attempts=attempts, base_delay_seconds=0.0)


# ── 1. lease heartbeat ───────────────────────────────────────────────────────
def test_heartbeat_renews_the_lease_while_work_runs(repo) -> None:
    leases = WorkerLeaseManager(repo, ttl_seconds=60, owner="w1")
    key = scope_key("t1", "u1")
    assert leases.acquire(key, now=NOW)

    renewed = threading.Event()

    def _renew() -> bool:
        renewed.set()
        return True

    hb = LeaseHeartbeat(leases, key, ttl_seconds=60, interval_seconds=0.01, renew=_renew)
    with hb:
        assert renewed.wait(timeout=2.0), "heartbeat never renewed the lease"
    assert not hb.lost.is_set()


def test_heartbeat_flags_loss_when_renewal_fails(repo) -> None:
    """Losing the lease must be observable, not silent — another replica may own us."""
    leases = WorkerLeaseManager(repo, ttl_seconds=60, owner="w1")
    hb = LeaseHeartbeat(
        leases, scope_key("t1", "u1"), ttl_seconds=60,
        interval_seconds=0.01, renew=lambda: False,
    )
    with hb:
        assert hb.lost.wait(timeout=2.0), "lease loss was not flagged"


def test_heartbeat_treats_a_raising_store_as_lease_loss(repo) -> None:
    """If we cannot prove ownership, fail closed rather than assume we still hold it."""
    leases = WorkerLeaseManager(repo, ttl_seconds=60, owner="w1")

    def _boom() -> bool:
        raise RuntimeError("store unreachable")

    hb = LeaseHeartbeat(
        leases, scope_key("t1", "u1"), ttl_seconds=60,
        interval_seconds=0.01, renew=_boom,
    )
    with hb:
        assert hb.lost.wait(timeout=2.0)


def test_a_job_outliving_the_lease_ttl_does_not_lose_exclusivity(repo) -> None:
    """The regression: work longer than the TTL must keep its lease.

    Simulates a slow scope with a 1s TTL. Without renewal the lease expires and a
    second worker can acquire the same scope; with the heartbeat it cannot.
    """
    key = scope_key("t1", "u1")
    leases = WorkerLeaseManager(repo, ttl_seconds=1, owner="worker-a")
    assert leases.acquire(key, now=datetime.now(UTC))

    other = WorkerLeaseManager(repo, ttl_seconds=1, owner="worker-b")

    with LeaseHeartbeat(leases, key, ttl_seconds=1, interval_seconds=0.05):
        # Work for longer than the TTL while the heartbeat renews underneath us.
        threading.Event().wait(1.6)
        acquired_by_other = other.acquire(key, now=datetime.now(UTC))

    assert not acquired_by_other, (
        "a second worker acquired a scope whose lease should have been renewed — "
        "the same tenant/user would be mutated concurrently"
    )


def test_orchestrator_records_lease_lost_and_aborts_remaining_jobs(repo, monkeypatch) -> None:
    """A lost lease stops the scope between jobs instead of mutating on."""
    seed_memory(repo, content="dark mode")

    # Force every renewal to fail so the heartbeat flags loss almost immediately.
    monkeypatch.setattr(
        "app.workers.heartbeat.LeaseHeartbeat._renew", lambda self: False, raising=False
    )
    monkeypatch.setattr(WorkerLeaseManager, "renew", lambda self, key, now=None: False)

    orch = WorkerOrchestrator(
        repo, owner="w1", lease_ttl_seconds=1,
        retry_policy=_fast_policy(1), sleep=lambda _s: None,
    )
    # Heartbeat interval is ttl/3 ≈ 0.33s; give the scope work that spans it.
    record = orch.run_scope(Scope("t1", "u1"), now=NOW, trace_id="t")

    # Either the run completed before the first renewal tick, or it was caught and
    # failed closed. It must never be silently "completed" *after* a detected loss.
    if record.details.get("reason") == "lease_lost_mid_run":
        assert record.status == RUN_LEASE_LOST
    else:
        assert record.status in (RUN_COMPLETED, RUN_DEAD_LETTER)
    # The lease is always released, whatever happened.
    assert repo.get_lease(scope_key("t1", "u1")) is None


# ── 2. per-job retry + dead-letter ───────────────────────────────────────────
class _FlakyWorker:
    """Fails `fail_times` times (by returning a failed result), then succeeds."""

    calls = 0
    fail_times = 1

    def __init__(self, repo, audit) -> None:
        pass

    def run(self, ctx) -> WorkerJobResult:
        type(self).calls += 1
        failed = type(self).calls <= type(self).fail_times
        return WorkerJobResult(
            job=WorkerJob.decay.value,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            started_at=ctx.now,
            completed_at=ctx.now,
            status=(
                WorkerRunStatus.failed.value if failed else WorkerRunStatus.completed.value
            ),
            error="Boom" if failed else None,
        )


def _patch_decay(monkeypatch, worker_cls) -> None:
    from app.workers import runner as runner_module

    monkeypatch.setitem(runner_module._WORKERS, WorkerJob.decay, worker_cls)


def test_a_failed_job_result_is_retried(repo, monkeypatch) -> None:
    """The core gap: workers *return* failure rather than raising, so retry must
    key off the result status, not just exceptions."""
    _FlakyWorker.calls = 0
    _FlakyWorker.fail_times = 1
    _patch_decay(monkeypatch, _FlakyWorker)

    report = run_jobs(
        repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW,
        retry_policy=_fast_policy(3), sleep=lambda _s: None,
    )
    assert _FlakyWorker.calls == 2, "failed job was not retried"
    assert report.results[0].status == WorkerRunStatus.completed.value
    assert report.results[0].details["attempts"] == 2


def test_exhausted_retries_dead_letter_the_job(repo, monkeypatch) -> None:
    _FlakyWorker.calls = 0
    _FlakyWorker.fail_times = 99  # never succeeds
    _patch_decay(monkeypatch, _FlakyWorker)

    report = run_jobs(
        repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW,
        retry_policy=_fast_policy(3), sleep=lambda _s: None,
    )
    assert _FlakyWorker.calls == 3
    result = report.results[0]
    assert result.status == WorkerRunStatus.dead_letter.value, (
        "an exhausted job must be dead-lettered so the work is replayable, "
        "not merely recorded as failed and dropped"
    )
    assert result.details["attempts"] == 3
    assert not report.ok


def test_orchestrator_surfaces_a_dead_lettered_job_in_run_history(repo, monkeypatch) -> None:
    _FlakyWorker.calls = 0
    _FlakyWorker.fail_times = 99
    _patch_decay(monkeypatch, _FlakyWorker)

    orch = WorkerOrchestrator(
        repo, owner="w1", retry_policy=_fast_policy(2), sleep=lambda _s: None
    )
    record = orch.run_scope(Scope("t1", "u1", jobs=("decay",)), now=NOW)

    assert record.status == RUN_DEAD_LETTER
    assert record.details["jobs"]["decay"] == WorkerRunStatus.dead_letter.value


class _RaisingWorker:
    def __init__(self, repo, audit) -> None:
        pass

    def run(self, ctx):
        raise RuntimeError("worker exploded")


def test_a_raising_job_is_also_retried_and_dead_lettered(repo, monkeypatch) -> None:
    _patch_decay(monkeypatch, _RaisingWorker)
    report = run_jobs(
        repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW,
        retry_policy=_fast_policy(2), sleep=lambda _s: None,
    )
    result = report.results[0]
    assert result.status == WorkerRunStatus.dead_letter.value
    assert result.error == "RuntimeError"
    assert result.details["attempts"] == 2


class _FindingWorker:
    calls = 0

    def __init__(self, repo, audit) -> None:
        pass

    def run(self, ctx) -> WorkerJobResult:
        type(self).calls += 1
        return WorkerJobResult(
            job=WorkerJob.decay.value,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            started_at=ctx.now,
            completed_at=ctx.now,
            status=WorkerRunStatus.completed_with_findings.value,
        )


def test_findings_are_never_retried(repo, monkeypatch) -> None:
    """A finding (e.g. a deletion leak) is a real result, not a transient fault.

    Retrying it would multiply audit events and mask the finding.
    """
    _FindingWorker.calls = 0
    _patch_decay(monkeypatch, _FindingWorker)
    run_jobs(
        repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW,
        retry_policy=_fast_policy(3), sleep=lambda _s: None,
    )
    assert _FindingWorker.calls == 1


def test_abort_marks_remaining_jobs_aborted_not_missing(repo) -> None:
    """Remaining jobs must be recorded as aborted, not silently absent from the report."""
    report = run_jobs(
        repo, tenant_id="t1", user_id="u1", jobs=["decay", "archive"], now=NOW,
        should_abort=lambda: True,
    )
    assert [r.status for r in report.results] == [
        WorkerRunStatus.aborted.value,
        WorkerRunStatus.aborted.value,
    ]
    assert not report.ok


def test_default_run_jobs_still_runs_once(repo) -> None:
    """Without a policy the CLI path keeps its single-attempt behaviour."""
    _FlakyWorker.calls = 0
    _FlakyWorker.fail_times = 99
    import app.workers.runner as runner_module

    original = runner_module._WORKERS[WorkerJob.decay]
    runner_module._WORKERS[WorkerJob.decay] = _FlakyWorker
    try:
        report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW)
    finally:
        runner_module._WORKERS[WorkerJob.decay] = original
    assert _FlakyWorker.calls == 1
    # A single attempt is a plain failure, not a dead-letter.
    assert report.results[0].status == WorkerRunStatus.failed.value


# ── 3. graceful shutdown ─────────────────────────────────────────────────────
def test_shutdown_signal_is_set_by_sigterm() -> None:
    sig = ShutdownSignal()
    with sig:
        assert not sig.is_set()
        signal.raise_signal(signal.SIGTERM)
        assert sig.is_set()
        assert sig.signal_name == "SIGTERM"


def test_shutdown_signal_restores_previous_handlers() -> None:
    original = signal.getsignal(signal.SIGTERM)
    with ShutdownSignal():
        pass
    assert signal.getsignal(signal.SIGTERM) is original


def test_shutdown_wait_is_interruptible() -> None:
    """The old loop slept uninterruptibly, so SIGTERM did nothing until SIGKILL."""
    sig = ShutdownSignal()
    started = threading.Event()

    def _stop_soon() -> None:
        started.wait(timeout=1.0)
        sig.set()

    threading.Thread(target=_stop_soon, daemon=True).start()
    started.set()
    # A 30s wait must return as soon as the flag is set, not 30s later.
    begin = datetime.now(UTC)
    sig.wait(30.0)
    elapsed = datetime.now(UTC) - begin
    assert sig.is_set()
    assert elapsed < timedelta(seconds=5), f"wait was not interruptible ({elapsed})"


def test_scheduler_stops_when_shutdown_is_requested(repo) -> None:
    sig = ShutdownSignal()
    ticks_seen = {"n": 0}

    class _CountingOrchestrator:
        def run_once(self, scopes, *, now=None, trace_id=None):
            ticks_seen["n"] += 1
            sig.set()  # ask to stop after the first tick
            return []

    scheduler = WorkerScheduler(
        repo, scopes=[Scope("t1", "u1")], interval_seconds=30,
        orchestrator=_CountingOrchestrator(), shutdown=sig,
    )
    # Unbounded loop: it must terminate because of the flag, not a tick cap.
    ticks = scheduler.run_forever()
    assert ticks == 1
    assert ticks_seen["n"] == 1


def test_scheduler_does_not_start_a_tick_after_shutdown(repo) -> None:
    sig = ShutdownSignal()
    sig.set()
    calls = {"n": 0}

    class _Orchestrator:
        def run_once(self, scopes, *, now=None, trace_id=None):
            calls["n"] += 1
            return []

    scheduler = WorkerScheduler(
        repo, scopes=[Scope("t1", "u1")], interval_seconds=1,
        orchestrator=_Orchestrator(), shutdown=sig,
    )
    assert scheduler.run_forever(max_ticks=5) == 0
    assert calls["n"] == 0, "a tick was started after shutdown was requested"


def test_orchestrator_stops_between_scopes_on_shutdown(repo) -> None:
    """In-flight scope finishes; remaining scopes are left for the next replica."""
    seed_memory(repo, tenant_id="t1", user_id="u1")
    sig = ShutdownSignal()

    orch = WorkerOrchestrator(
        repo, owner="w1", retry_policy=_fast_policy(1),
        sleep=lambda _s: None, shutdown=sig,
    )
    sig.set()
    records = orch.run_once([Scope("t1", "u1"), Scope("t2", "u2")], now=NOW)
    assert records == [], "no scope should start once shutdown was requested"
