"""Lifecycle worker base + runner: audit evidence, run status/metrics, job
selection, tenant scoping, and the guarantee that a worker failure never blocks
chat (workers are off the request path)."""

from __future__ import annotations

from app.schemas.memory import ChatRequest
from app.workers.lifecycle import LifecycleWorker, WorkerContext
from app.workers.metrics import summarize_worker_results
from app.workers.runner import run_jobs
from app.workers.schemas import (
    DEFAULT_JOB_ORDER,
    WORKER_COMPLETED,
    WORKER_FAILED,
    WORKER_STARTED,
    WorkerJob,
    WorkerRunStatus,
)

from ._worker_helpers import NOW, seed_memory


def _ctx(**kw) -> WorkerContext:
    kw.setdefault("tenant_id", "t1")
    kw.setdefault("user_id", "u1")
    kw.setdefault("now", NOW)
    return WorkerContext(**kw)


class _BoomWorker(LifecycleWorker):
    job = WorkerJob.decay

    def _execute(self, ctx, result) -> None:
        raise RuntimeError("intentional worker failure")


def test_run_emits_started_and_completed_audit(repo) -> None:
    seed_memory(repo, importance=8, age_days=400)
    from app.workers.decay import DecayWorker

    result = DecayWorker(repo, age_threshold_days=90).run(_ctx())
    actions = [e.action for e in repo.list_audit("t1", "u1")]
    assert WORKER_STARTED in actions
    assert WORKER_COMPLETED in actions
    assert result.completed_at is not None
    assert result.duration_ms >= 0
    assert result.audit_event_ids  # the started/completed ids are tracked


def test_worker_failure_is_caught_and_recorded(repo) -> None:
    result = _BoomWorker(repo).run(_ctx())
    assert result.status == WorkerRunStatus.failed.value
    assert result.error == "RuntimeError"
    assert result.error_count == 1
    actions = {e.action for e in repo.list_audit("t1", "u1")}
    assert WORKER_FAILED in actions


def test_worker_failure_does_not_block_chat(gateway, repo) -> None:
    # A worker blowing up must not affect the chat request path at all.
    _BoomWorker(repo).run(_ctx())
    resp = gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message="Remember I prefer dark mode."),
        trace_id="trace-after-worker-failure",
    )
    assert resp.assistant_message  # chat still answers normally
    assert resp.trace_id == "trace-after-worker-failure"


def test_runner_all_runs_every_job(repo) -> None:
    seed_memory(repo, importance=8, age_days=400)
    report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["all"], now=NOW)
    ran = {r.job for r in report.results}
    assert ran == {j.value for j in DEFAULT_JOB_ORDER}
    assert report.ok


def test_runner_specific_jobs(repo) -> None:
    report = run_jobs(
        repo, tenant_id="t1", user_id="u1", jobs=["decay", "archive"], now=NOW
    )
    assert [r.job for r in report.results] == ["decay", "archive"]


def test_runner_report_to_dict_is_content_free(repo) -> None:
    seed_memory(repo, content="secret sauce recipe", importance=8, age_days=400)
    report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW)
    data = report.to_dict()
    assert "secret sauce recipe" not in str(data)
    assert data["totals"]["jobs"] == 1
    assert data["results"][0]["job"] == "decay"


def test_reflection_skipped_by_default(repo) -> None:
    seed_memory(repo)
    report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["reflection"], now=NOW)
    assert report.results[0].status == WorkerRunStatus.skipped.value


def test_runner_is_tenant_scoped(repo) -> None:
    mine = seed_memory(repo, tenant_id="t1", importance=8, age_days=400)
    other = seed_memory(repo, tenant_id="t2", importance=8, age_days=400)
    run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW)
    assert repo.get_memory("t1", "u1", mine.id).importance < 8
    assert repo.get_memory("t2", "u1", other.id).importance == 8


def test_summarize_worker_results(repo) -> None:
    seed_memory(repo, importance=8, age_days=400)
    report = run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["all"], now=NOW)
    summary = summarize_worker_results(report.results)
    assert summary["jobs"] == len(DEFAULT_JOB_ORDER)
    assert summary["failed"] == 0
    assert "by_status" in summary and "by_job" in summary


def test_worker_run_is_traced(repo) -> None:
    """v1.8 (ADR-022): each job is a span under a minted worker correlation id, so a
    run is one correlated trace — without changing job behavior."""
    from app.observability import recent_spans, reset_spans

    seed_memory(repo, importance=8, age_days=400)
    reset_spans()
    run_jobs(repo, tenant_id="t1", user_id="u1", jobs=["decay"], now=NOW)
    job_spans = [s for s in recent_spans(limit=512) if s["name"] == "worker.job"]
    assert job_spans and job_spans[0]["attributes"].get("job") == "decay"
    assert job_spans[0]["correlation_id"].startswith("worker-")
