"""Worker runner + CLI (v0.6).

Runs lifecycle jobs for an explicit tenant/user scope and returns structured
results. Scope is always explicit: a worker only ever processes the (tenant_id,
user_id) it is handed, which is how tenant isolation is guaranteed end to end
(invariant #1). Enumerating/scheduling scopes across the fleet is the
orchestrator's job (the Railway ``worker`` service) and is intentionally out of
scope here — see docs/background-lifecycle-workers.md.

Usage (local):
    python -m app.workers.runner --tenant t1 --user u1 --job all
    python -m app.workers.runner --tenant t1 --user u1 --job decay --job archive
    python -m app.workers.runner --tenant t1 --user u1 --job deletion_compaction
    python -m app.workers.runner --tenant t1 --user u1 --job deletion_verification --dry-run
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

from ..core.logging import get_logger
from ..db.factory import get_repository
from ..db.repository import Repository
from ..services.audit import AuditService
from .archive import ArchiveWorker
from .conflict_scan import ConflictScanWorker
from .decay import DecayWorker
from .deletion_compaction import DeletionCompactionWorker
from .deletion_verification import DeletionVerificationWorker
from .lifecycle import LifecycleWorker, WorkerContext
from .reflection import ReflectionWorker
from .retention import RetentionWorker
from .retry import RetryPolicy
from .schemas import (
    DEFAULT_JOB_ORDER,
    WorkerJob,
    WorkerJobResult,
    WorkerRunReport,
    WorkerRunStatus,
)

logger = get_logger("memoryops.workers.runner")

# Job → worker class. Single source of truth for the runner and the CLI.
_WORKERS: dict[WorkerJob, type[LifecycleWorker]] = {
    WorkerJob.decay: DecayWorker,
    WorkerJob.archive: ArchiveWorker,
    WorkerJob.retention: RetentionWorker,
    WorkerJob.deletion_compaction: DeletionCompactionWorker,
    WorkerJob.deletion_verification: DeletionVerificationWorker,
    WorkerJob.conflict_scan: ConflictScanWorker,
    WorkerJob.reflection: ReflectionWorker,
}


def _resolve_jobs(jobs: list[str]) -> list[WorkerJob]:
    if not jobs or "all" in jobs:
        return list(DEFAULT_JOB_ORDER)
    resolved: list[WorkerJob] = []
    for name in jobs:
        job = WorkerJob(name)  # raises ValueError on unknown job
        if job not in resolved:
            resolved.append(job)
    return resolved


def _run_one_job(
    job: WorkerJob,
    repo: Repository,
    audit: AuditService,
    ctx: WorkerContext,
    *,
    policy: RetryPolicy | None,
    sleep: Callable[[float], None],
) -> WorkerJobResult:
    """Run a single job, retrying a *failed* result up to the policy's budget.

    Retrying on the returned status (not just on a raised exception) is the point.
    Lifecycle workers catch their own errors and return
    ``status=failed`` rather than raising, so the orchestration-level
    ``run_with_retry`` around ``run_jobs`` only ever saw clean returns: a failing
    job was recorded as failed and then simply dropped — never retried, never
    dead-lettered. Findings (``completed_with_findings``) are real results, not
    faults, so they are never retried.
    """
    attempts = 0
    max_attempts = policy.max_attempts if policy else 1
    result: WorkerJobResult | None = None

    while attempts < max_attempts:
        attempts += 1
        worker = _WORKERS[job](repo, audit)
        try:
            result = worker.run(ctx)
        except Exception as exc:  # noqa: BLE001 — a raising worker is still retryable
            result = WorkerJobResult(
                job=job.value,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                started_at=ctx.now,
                completed_at=datetime.now(UTC),
                status=WorkerRunStatus.failed.value,
                error=type(exc).__name__,
            )
        if result.status != WorkerRunStatus.failed.value:
            break
        if attempts < max_attempts and policy is not None:
            logger.warning(
                "worker job failed; retrying",
                extra={
                    "event": "worker_job_retry",
                    "status": "failed",
                    "job": job.value,
                    "attempt": attempts,
                    "error": result.error,
                },
            )
            sleep(policy.delay_for(attempts))

    assert result is not None  # loop runs at least once
    result.details = {**result.details, "attempts": attempts}
    if result.status == WorkerRunStatus.failed.value and attempts >= max_attempts > 1:
        # Budget exhausted → dead-letter so the work is replayable, not just logged.
        result.status = WorkerRunStatus.dead_letter.value
        logger.warning(
            "worker job dead-lettered after exhausting retries",
            extra={
                "event": "worker_job_dead_letter",
                "status": "failed",
                "job": job.value,
                "attempts": attempts,
                "error": result.error,
            },
        )
    return result


def run_jobs(
    repo: Repository,
    *,
    tenant_id: str,
    user_id: str,
    jobs: list[str] | None = None,
    trace_id: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    audit: AuditService | None = None,
    retry_policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    should_abort: Callable[[], bool] | None = None,
) -> WorkerRunReport:
    """Run the selected lifecycle jobs for one tenant/user scope.

    Each job runs independently; one job failing is recorded in its result and
    never prevents the others from running (workers never block the pipeline).

    ``retry_policy`` enables per-job retry + dead-lettering (the orchestrator passes
    one; the CLI defaults to a single attempt). ``should_abort`` is polled before
    each job so a lost lease or a shutdown request stops the scope *between* jobs
    rather than mutating a scope this worker may no longer own — remaining jobs are
    recorded as ``aborted`` instead of silently vanishing from the report.
    """
    from ..observability import new_correlation_id, set_correlation_id, span

    audit = audit or AuditService(repo)
    ctx = WorkerContext(
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        now=now or datetime.now(UTC),
        dry_run=dry_run,
    )
    # v1.8: a worker run has no HTTP trace, so mint a correlation id; each job is a
    # span so a run is one correlated trace end to end (ADR-022).
    set_correlation_id(trace_id) if trace_id else new_correlation_id("worker")
    report = WorkerRunReport(started_at=ctx.now)
    aborted = False
    for job in _resolve_jobs(jobs or ["all"]):
        if aborted or (should_abort is not None and should_abort()):
            aborted = True
            report.add(
                WorkerJobResult(
                    job=job.value,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    started_at=ctx.now,
                    completed_at=datetime.now(UTC),
                    status=WorkerRunStatus.aborted.value,
                    details={"reason": "lease_lost_or_shutdown"},
                )
            )
            continue
        with span("worker.job", job=job.value, dry_run=dry_run):
            report.add(
                _run_one_job(job, repo, audit, ctx, policy=retry_policy, sleep=sleep)
            )
    report.completed_at = datetime.now(UTC)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MemoryOps AI — background lifecycle worker runner")
    ap.add_argument("--tenant", required=True, help="tenant_id scope")
    ap.add_argument("--user", required=True, help="user_id scope")
    ap.add_argument(
        "--job",
        action="append",
        default=[],
        choices=[*[j.value for j in WorkerJob], "all"],
        help="job(s) to run; repeatable. Default: all",
    )
    ap.add_argument("--trace-id", default=None)
    ap.add_argument("--dry-run", action="store_true", help="report candidates, make no changes")
    args = ap.parse_args(argv)

    report = run_jobs(
        get_repository(),
        tenant_id=args.tenant,
        user_id=args.user,
        jobs=args.job or ["all"],
        trace_id=args.trace_id,
        dry_run=args.dry_run,
    )
    print(json.dumps(report.to_dict(), indent=2))
    # Exit non-zero when a job failed or a verification finding surfaced, so the
    # runner is usable as a scheduled health check.
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
