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
