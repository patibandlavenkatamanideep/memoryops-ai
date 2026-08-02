"""Worker orchestration runtime (v0.8, ADR-012).

Proves the scheduled runtime: leased (duplicate runs prevented), retried,
recorded as run history, and dead-lettered on exhausted retries — all tenant
scoped, with one scope's failure never blocking another.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.schemas.memory import Status
from app.workers.locks import scope_key
from app.workers.orchestrator import (
    RUN_COMPLETED,
    RUN_DEAD_LETTER,
    RUN_LOCKED_SKIP,
    Scope,
    WorkerOrchestrator,
    parse_scopes,
    summarize_runtime_health,
)
from app.workers.retry import RetryPolicy
from app.workers.scheduler import WorkerScheduler

from ._worker_helpers import seed_memory

NOW = datetime(2026, 6, 22, tzinfo=UTC)


def _orch(repo, owner="worker-test", **kw):
    kw.setdefault("retry_policy", RetryPolicy(max_attempts=2, base_delay_seconds=0.0))
    kw.setdefault("sleep", lambda _s: None)
    return WorkerOrchestrator(repo, owner=owner, **kw)


def test_parse_scopes() -> None:
    scopes = parse_scopes("t1:u1, t2:u2 ,bad,:nouser,tenant:")
    assert scopes == [Scope("t1", "u1"), Scope("t2", "u2")]


def test_run_scope_records_history(repo) -> None:
    seed_memory(repo, content="dark mode", status=Status.active)
    rec = _orch(repo).run_scope(Scope("t1", "u1"), now=NOW, trace_id="x")

    assert rec.status == RUN_COMPLETED
    assert rec.attempts == 1
    assert rec.owner == "worker-test"
    history = repo.list_worker_runs(tenant_id="t1", user_id="u1")
    assert [r.id for r in history] == [rec.id]
    # Lease is released after the run so the next pass can acquire it.
    assert repo.get_lease(scope_key("t1", "u1")) is None


def test_duplicate_run_prevented_by_lease(repo) -> None:
    # Another owner holds a live lease → orchestrator skips, records locked_skip.
    repo.try_acquire_lease(
        scope_key("t1", "u1"), "other-worker",
        now=NOW, expires_at=NOW.replace(year=2027),
    )
    rec = _orch(repo).run_scope(Scope("t1", "u1"), now=NOW)
    assert rec.status == RUN_LOCKED_SKIP
    assert rec.attempts == 0
    # The other owner's lease is untouched (we never released someone else's lease).
    assert repo.get_lease(scope_key("t1", "u1")).owner == "other-worker"


def test_exhausted_retries_become_dead_letter(repo, monkeypatch) -> None:
    def _boom(*a, **kw):
        raise RuntimeError("store down")

    monkeypatch.setattr("app.workers.orchestrator.run_jobs", _boom)
    rec = _orch(repo).run_scope(Scope("t1", "u1"), now=NOW)

    assert rec.status == RUN_DEAD_LETTER
    assert rec.attempts == 2
    assert rec.error == "RuntimeError"
    # Lease released even though the work failed → scope not deadlocked.
    assert repo.get_lease(scope_key("t1", "u1")) is None
    dead = repo.list_worker_runs(status=RUN_DEAD_LETTER)
    assert len(dead) == 1


def test_run_once_is_tenant_scoped_and_independent(repo) -> None:
    seed_memory(repo, tenant_id="t1", status=Status.active)
    seed_memory(repo, tenant_id="t2", status=Status.active)
    recs = _orch(repo).run_once([Scope("t1", "u1"), Scope("t2", "u1")], now=NOW)

    assert {r.tenant_id for r in recs} == {"t1", "t2"}
    assert repo.list_worker_runs(tenant_id="t1") and repo.list_worker_runs(tenant_id="t2")


def test_second_pass_is_idempotent(repo) -> None:
    seed_memory(repo, status=Status.active)
    orch = _orch(repo)
    orch.run_once([Scope("t1", "u1")], now=NOW)
    orch.run_once([Scope("t1", "u1")], now=NOW)
    runs = repo.list_worker_runs(tenant_id="t1", user_id="u1")
    assert len(runs) == 2  # both passes recorded
    assert all(r.status == RUN_COMPLETED for r in runs)


def test_runtime_health_summary(repo, monkeypatch) -> None:
    seed_memory(repo, status=Status.active)
    orch = _orch(repo)
    orch.run_scope(Scope("t1", "u1"), now=NOW)  # completed
    # Force a dead-letter for a second scope.
    monkeypatch.setattr(
        "app.workers.orchestrator.run_jobs", lambda *a, **kw: (_ for _ in ()).throw(OSError())
    )
    orch.run_scope(Scope("t2", "u2"), now=NOW)

    health = summarize_runtime_health(repo)
    assert health["runs_observed"] == 2
    assert health["dead_letter_count"] == 1
    assert "t1:u1" in health["last_run_per_scope"]


def test_scheduler_run_forever_bounded_by_max_ticks(repo) -> None:
    seed_memory(repo, status=Status.active)
    slept: list[float] = []
    sched = WorkerScheduler(
        repo, scopes=[Scope("t1", "u1")], interval_seconds=5,
        orchestrator=_orch(repo), sleep=slept.append,
    )
    ticks = sched.run_forever(max_ticks=3)
    assert ticks == 3
    # Sleeps only between ticks, not after the last one.
    assert slept == [5, 5]
    assert len(repo.list_worker_runs(tenant_id="t1", user_id="u1")) == 3


# ── per-job retry, dead-letter, and cooperative shutdown ─────────────────────
# Retry used to wrap `run_jobs` as a whole, but lifecycle workers catch their own
# errors and *return* status=failed rather than raising — so the wrapper only saw
# clean returns and a failing job was recorded then dropped: never retried, never
# dead-lettered. Full coverage in tests/test_worker_reliability.py.
def test_orchestrator_dead_letters_a_persistently_failing_job(repo, monkeypatch) -> None:
    from app.workers import runner as runner_module
    from app.workers.schemas import WorkerJob, WorkerJobResult, WorkerRunStatus

    calls = {"n": 0}

    class _AlwaysFails:
        def __init__(self, repo, audit) -> None:
            pass

        def run(self, ctx) -> WorkerJobResult:
            calls["n"] += 1
            return WorkerJobResult(
                job=WorkerJob.decay.value,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                started_at=ctx.now,
                completed_at=ctx.now,
                status=WorkerRunStatus.failed.value,
                error="Boom",
            )

    monkeypatch.setitem(runner_module._WORKERS, WorkerJob.decay, _AlwaysFails)

    record = _orch(repo).run_scope(Scope("t1", "u1", jobs=("decay",)), now=NOW)

    assert calls["n"] == 2, "the failing job must be retried, not recorded once and dropped"
    assert record.status == RUN_DEAD_LETTER
    assert record.details["jobs"]["decay"] == WorkerRunStatus.dead_letter.value


def test_orchestrator_stops_between_scopes_when_shutdown_is_requested(repo) -> None:
    """SIGTERM must stop the pass at a scope boundary, releasing the lease cleanly."""
    from app.workers.shutdown import ShutdownSignal

    seed_memory(repo, status=Status.active)
    shutdown = ShutdownSignal()
    orch = _orch(repo, shutdown=shutdown)

    shutdown.set()
    records = orch.run_once([Scope("t1", "u1"), Scope("t2", "u2")], now=NOW)

    assert records == []
    assert repo.get_lease(scope_key("t1", "u1")) is None


def test_lease_is_released_even_when_every_job_dead_letters(repo, monkeypatch) -> None:
    from app.workers import runner as runner_module
    from app.workers.schemas import WorkerJob

    class _Explodes:
        def __init__(self, repo, audit) -> None:
            pass

        def run(self, ctx):
            raise RuntimeError("worker exploded")

    monkeypatch.setitem(runner_module._WORKERS, WorkerJob.decay, _Explodes)
    _orch(repo).run_scope(Scope("t1", "u1", jobs=("decay",)), now=NOW)
    # A stuck lease would make the next replica skip this scope for a full TTL.
    assert repo.get_lease(scope_key("t1", "u1")) is None
