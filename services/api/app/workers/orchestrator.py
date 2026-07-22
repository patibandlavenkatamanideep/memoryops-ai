"""Worker runtime orchestration (v0.8, ADR-012).

Turns the v0.6/v0.7 lifecycle workers from callable functions into an operable,
scheduled runtime. For each explicit ``(tenant, user)`` scope the orchestrator:

  1. acquires a **lease** so duplicate concurrent runs are prevented (locks.py);
  2. runs the lifecycle jobs (`run_jobs`) under a **retry/backoff** policy that
     absorbs transient store faults (retry.py);
  3. persists a content-free **run-history** record (and a **dead-letter** record
     if retries are exhausted);
  4. always **releases** the lease, even on failure.

Tenant isolation is preserved: each scope is processed independently through the
repository's scoped methods, and one scope failing never blocks another. Scope
enumeration stays explicit (no unbounded cross-tenant scan) — see ADR-010/012.
"""

from __future__ import annotations

import os
import socket
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..core.config import get_settings
from ..core.logging import get_logger
from ..db.entities import WorkerRunRecord
from ..db.repository import Repository
from ..services.audit import AuditService
from .locks import WorkerLeaseManager, scope_key
from .retry import RetryPolicy, run_with_retry
from .runner import run_jobs
from .schemas import WorkerRunReport, WorkerRunStatus

logger = get_logger("memoryops.workers.orchestrator")

# Run-history statuses (superset of WorkerRunStatus: adds runtime-level outcomes).
RUN_COMPLETED = WorkerRunStatus.completed.value
RUN_WITH_FINDINGS = WorkerRunStatus.completed_with_findings.value
RUN_FAILED = WorkerRunStatus.failed.value
RUN_LOCKED_SKIP = "locked_skip"
RUN_DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    user_id: str
    jobs: tuple[str, ...] = ("all",)


def parse_scopes(raw: str) -> list[Scope]:
    """Parse ``"tenant:user,tenant2:user2"`` into scopes (jobs default to all)."""
    scopes: list[Scope] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        tenant, _, user = chunk.partition(":")
        if tenant and user:
            scopes.append(Scope(tenant_id=tenant.strip(), user_id=user.strip()))
    return scopes


def default_owner() -> str:
    """Stable-enough identity for a worker replica: host:pid:rand."""
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _report_status(report: WorkerRunReport) -> str:
    statuses = {r.status for r in report.results}
    if RUN_FAILED in statuses:
        return RUN_FAILED
    if RUN_WITH_FINDINGS in statuses:
        return RUN_WITH_FINDINGS
    return RUN_COMPLETED


@dataclass
class WorkerOrchestrator:
    repo: Repository
    owner: str = field(default_factory=default_owner)
    lease_ttl_seconds: int | None = None
    retry_policy: RetryPolicy | None = None
    audit: AuditService | None = None
    sleep: Callable[[float], None] | None = None

    def __post_init__(self) -> None:
        s = get_settings()
        self._leases = WorkerLeaseManager(
            self.repo,
            ttl_seconds=self.lease_ttl_seconds or s.worker_lease_ttl_seconds,
            owner=self.owner,
        )
        self._policy = self.retry_policy or RetryPolicy(
            max_attempts=s.worker_max_attempts,
            base_delay_seconds=s.worker_backoff_base_seconds,
            backoff_factor=s.worker_backoff_factor,
            max_delay_seconds=s.worker_backoff_max_seconds,
        )
        self._audit = self.audit or AuditService(self.repo)

    def run_scope(
        self, scope: Scope, *, now: datetime | None = None, trace_id: str | None = None
    ) -> WorkerRunRecord:
        now = now or datetime.now(UTC)
        key = scope_key(scope.tenant_id, scope.user_id)
        jobs = list(scope.jobs)

        if not self._leases.acquire(key, now=now):
            # Another replica holds the lease → skip; record the duplicate-prevented
            # outcome so it is observable, but do no work.
            return self._record(
                scope, jobs, status=RUN_LOCKED_SKIP, attempts=0, now=now,
                trace_id=trace_id, details={"reason": "lease_held_by_other"},
            )

        try:
            outcome = run_with_retry(
                lambda: run_jobs(
                    self.repo,
                    tenant_id=scope.tenant_id,
                    user_id=scope.user_id,
                    jobs=jobs,
                    trace_id=trace_id,
                    now=now,
                    audit=self._audit,
                ),
                self._policy,
                sleep=self.sleep or time.sleep,
            )
            if outcome.ok and outcome.value is not None:
                report = outcome.value
                return self._record(
                    scope, jobs, status=_report_status(report),
                    attempts=outcome.attempts, now=now, trace_id=trace_id,
                    report=report,
                    details={"jobs": {r.job: r.status for r in report.results}},
                )
            # Retries exhausted on a transient fault → dead-letter, never lost.
            logger.warning(
                "worker scope dead-lettered",
                extra={"event": "worker_dead_letter", "status": "failed",
                       "attempts": outcome.attempts},
            )
            return self._record(
                scope, jobs, status=RUN_DEAD_LETTER, attempts=outcome.attempts,
                now=now, trace_id=trace_id, error=outcome.error,
                details={"reason": "retries_exhausted"},
            )
        finally:
            self._leases.release(key)

    def run_once(
        self,
        scopes: list[Scope],
        *,
        now: datetime | None = None,
        trace_id: str | None = None,
    ) -> list[WorkerRunRecord]:
        """One scheduling pass over all scopes. Scopes are independent."""
        records: list[WorkerRunRecord] = []
        for scope in scopes:
            records.append(self.run_scope(scope, now=now, trace_id=trace_id))
        return records

    # ── helpers ────────────────────────────────────────────────────────────────
    def _record(
        self,
        scope: Scope,
        jobs: list[str],
        *,
        status: str,
        attempts: int,
        now: datetime,
        trace_id: str | None,
        report: WorkerRunReport | None = None,
        error: str | None = None,
        details: dict | None = None,
    ) -> WorkerRunRecord:
        record = WorkerRunRecord(
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            status=status,
            jobs=jobs,
            attempts=attempts,
            scanned_count=report.scanned_count if report else 0,
            changed_count=report.changed_count if report else 0,
            skipped_count=report.skipped_count if report else 0,
            error_count=report.error_count if report else 0,
            owner=self.owner,
            trace_id=trace_id,
            error=error,
            details=details or {},
            started_at=now,
            completed_at=datetime.now(UTC),
        )
        return self.repo.add_worker_run(record)


def summarize_runtime_health(repo: Repository, *, limit: int = 200) -> dict:
    """Content-free operational health view over recent worker runs (v0.8).

    Global operator concern → reads via the explicit cross-tenant operational
    path, not the tenant-scoped one (which would raise). Raises
    ``OperationalAccessUnavailable`` when no operational connection is configured;
    callers degrade gracefully.
    """
    runs = repo.list_worker_runs_operational(limit=limit)
    by_status: dict[str, int] = {}
    last_per_scope: dict[str, dict] = {}
    for r in runs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        key = f"{r.tenant_id}:{r.user_id}"
        if key not in last_per_scope:  # runs are newest-first
            last_per_scope[key] = {
                "status": r.status,
                "attempts": r.attempts,
                "started_at": r.started_at.isoformat(),
            }
    return {
        "runs_observed": len(runs),
        "by_status": by_status,
        "dead_letter_count": by_status.get(RUN_DEAD_LETTER, 0),
        "failed_count": by_status.get(RUN_FAILED, 0),
        "with_findings_count": by_status.get(RUN_WITH_FINDINGS, 0),
        "locked_skip_count": by_status.get(RUN_LOCKED_SKIP, 0),
        "last_run_per_scope": last_per_scope,
    }
