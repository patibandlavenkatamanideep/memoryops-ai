"""Background memory lifecycle workers — shared base + context (v0.6, ADR-010).

These workers maintain memory *after* it is captured: decay, archive, deletion
verification, conflict scan, and (optional) reflection. They are not part of the
chat request path. Every worker:

  * is tenant + user scoped — it only ever reads/writes through the repository's
    scoped methods, so it cannot touch another tenant's memory (invariant #1);
  * is idempotent and safe to retry — re-running produces no further change once
    a memory has been processed (markers live under ``metadata["lifecycle"]``);
  * never resurrects deleted memory — it operates on active rows and the deletion
    guarantee (invariant #2) is preserved by the repository's scoped reads;
  * writes audit evidence for every action (invariant #7); and
  * never blocks chat — a worker failure is caught here and recorded, not raised.

The policy broker stays authoritative: workers may *demote, archive, or flag*
memory and propose review candidates, but they do not bypass policy to promote
or create active memory.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..core.logging import get_logger
from ..db.entities import StoredMemory
from ..db.repository import Repository
from ..services.audit import AuditService
from .schemas import (
    WORKER_COMPLETED,
    WORKER_FAILED,
    WORKER_STARTED,
    WorkerJob,
    WorkerJobResult,
    WorkerRunStatus,
)

logger = get_logger("memoryops.workers")

# Where idempotency / bookkeeping markers live on a memory. Content-free.
LIFECYCLE_META_KEY = "lifecycle"

_DELETED = "deleted"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class WorkerContext:
    """Tenant-scoped execution context for one worker run.

    ``now`` is injectable so age-based eligibility is deterministic in tests.
    """

    tenant_id: str
    user_id: str
    trace_id: str | None = None
    now: datetime = field(default_factory=_now)
    # When set, mutating workers only report candidates and make no changes.
    dry_run: bool = False


def lifecycle_meta(memory: StoredMemory) -> dict:
    """Return the (copied-safe) lifecycle bookkeeping sub-dict for a memory."""
    meta = memory.metadata.get(LIFECYCLE_META_KEY)
    return dict(meta) if isinstance(meta, dict) else {}


def set_lifecycle_meta(memory: StoredMemory, updates: dict) -> None:
    meta = lifecycle_meta(memory)
    meta.update(updates)
    memory.metadata[LIFECYCLE_META_KEY] = meta


def age_days(memory: StoredMemory, now: datetime) -> int:
    created = memory.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max(0, (now - created).days)


class LifecycleWorker(ABC):
    """Base class: wraps a job in started/completed/failed audit + result book."""

    job: WorkerJob

    def __init__(self, repo: Repository, audit: AuditService | None = None) -> None:
        self._repo = repo
        self._audit = audit or AuditService(repo)

    # Subclasses implement the actual scan, mutating ``result`` in place. They
    # must NOT touch deleted memory and must stay within the ctx scope.
    @abstractmethod
    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None: ...

    def run(self, ctx: WorkerContext) -> WorkerJobResult:
        result = WorkerJobResult(
            job=self.job.value,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            started_at=ctx.now,
        )
        started = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=WORKER_STARTED,
            reason=f"lifecycle worker '{self.job.value}' started",
            trace_id=ctx.trace_id,
            metadata={"job": self.job.value, "dry_run": ctx.dry_run},
        )
        result.audit_event_ids.append(started.id)
        try:
            self._execute(ctx, result)
        except Exception as exc:  # noqa: BLE001 — workers must never raise into callers
            # A worker failure must not block chat or other jobs (invariant #4).
            result.status = WorkerRunStatus.failed.value
            result.error = type(exc).__name__
            result.error_count += 1
            result.completed_at = _now()
            failed = self._audit.record(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                action=WORKER_FAILED,
                reason=f"lifecycle worker '{self.job.value}' failed: {type(exc).__name__}",
                trace_id=ctx.trace_id,
                metadata={"job": self.job.value, "error": type(exc).__name__},
            )
            result.audit_event_ids.append(failed.id)
            logger.warning(
                "lifecycle worker failed",
                extra={
                    "event": WORKER_FAILED,
                    "job": self.job.value,
                    "error": type(exc).__name__,
                    "status": "failed",
                },
            )
            return result

        result.completed_at = _now()
        completed = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=WORKER_COMPLETED,
            reason=(
                f"lifecycle worker '{self.job.value}' completed: "
                f"scanned={result.scanned_count} changed={result.changed_count} "
                f"skipped={result.skipped_count} errors={result.error_count}"
            ),
            trace_id=ctx.trace_id,
            metadata={
                "job": self.job.value,
                "scanned": result.scanned_count,
                "changed": result.changed_count,
                "skipped": result.skipped_count,
                "errors": result.error_count,
                "status": result.status,
            },
        )
        result.audit_event_ids.append(completed.id)
        logger.info(
            "lifecycle worker completed",
            extra={
                "event": WORKER_COMPLETED,
                "job": self.job.value,
                "scanned": result.scanned_count,
                "changed": result.changed_count,
                "status": result.status,
            },
        )
        return result

    # ── shared helpers ────────────────────────────────────────────────────────
    def _active_memories(self, ctx: WorkerContext) -> list[StoredMemory]:
        """Active, non-deleted memory in scope (deletion guarantee preserved)."""
        rows = self._repo.list_memories(
            ctx.tenant_id, ctx.user_id, status="active", include_deleted=False
        )
        # Defense in depth: never hand a deleted row to a mutating worker.
        return [m for m in rows if m.status.value != _DELETED]
