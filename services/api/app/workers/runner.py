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
    python -m app.workers.runner --tenant t1 --user u1 --job deletion_verification --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from ..db.factory import get_repository
from ..db.repository import Repository
from ..services.audit import AuditService
from .archive import ArchiveWorker
from .conflict_scan import ConflictScanWorker
from .decay import DecayWorker
from .deletion_verification import DeletionVerificationWorker
from .lifecycle import LifecycleWorker, WorkerContext
from .reflection import ReflectionWorker
from .schemas import DEFAULT_JOB_ORDER, WorkerJob, WorkerRunReport

# Job → worker class. Single source of truth for the runner and the CLI.
_WORKERS: dict[WorkerJob, type[LifecycleWorker]] = {
    WorkerJob.decay: DecayWorker,
    WorkerJob.archive: ArchiveWorker,
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
) -> WorkerRunReport:
    """Run the selected lifecycle jobs for one tenant/user scope.

    Each job runs independently; one job failing is recorded in its result and
    never prevents the others from running (workers never block the pipeline).
    """
    audit = audit or AuditService(repo)
    ctx = WorkerContext(
        tenant_id=tenant_id,
        user_id=user_id,
        trace_id=trace_id,
        now=now or datetime.now(UTC),
        dry_run=dry_run,
    )
    report = WorkerRunReport(started_at=ctx.now)
    for job in _resolve_jobs(jobs or ["all"]):
        worker = _WORKERS[job](repo, audit)
        report.add(worker.run(ctx))
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
