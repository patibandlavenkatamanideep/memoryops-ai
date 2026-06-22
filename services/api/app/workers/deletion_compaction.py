"""Deletion compaction worker (v0.7, ADR-011).

The next layer after deletion *verification*. v0.6 proves soft-deleted memory is
unreachable (logical deletion). This worker goes further: for soft-deleted memory
that has passed its retention/grace window it **clears the retrievable content and
vector material**, preserves the governance tombstone + audit trail, and then
**verifies** the purge — recording audit evidence for every step.

Safety rails (enforced here + in the repository + in tests):
  * only ``status='deleted'`` rows are ever eligible — active/archived memory is
    never compacted, deleted memory is never resurrected (invariants #1, #2);
  * eligibility also requires the memory to have been deleted for at least
    ``workers_compaction_min_age_days`` (a retention window);
  * idempotent — already-compacted rows are filtered out by the repository, so a
    re-run does no further destructive work and does not corrupt the tombstone;
  * tenant scoped — all reads/writes go through the repository's scoped methods;
  * fail-safe — a per-memory purge that does not verify is recorded as a finding
    (``completed_with_findings``), never silently passed; the worker never raises
    into the chat path.

What is cleared: ``content``, normalized content, embedding/vector material, and
the provenance excerpt. What is preserved: memory id, tenant/user, ``status``
(stays ``deleted``), ``deleted_at``, ``created_at``, ``source.kind``, and the full
audit trail. Audit metadata stays content-free — ids, counts, flags only.

This is **not** crypto-shred and does not claim database-page / ANN-index physical
byte reclamation — see docs/deletion-compaction.md and ADR-011.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..core.config import get_settings
from ..db.entities import StoredMemory
from ..db.repository import Repository
from ..services.audit import AuditService
from .lifecycle import LifecycleWorker, WorkerContext
from .schemas import (
    DELETION_COMPACTION_COMPLETED,
    DELETION_COMPACTION_FAILED,
    DELETION_COMPACTION_SKIPPED,
    DELETION_COMPACTION_STARTED,
    MEMORY_CONTENT_COMPACTED,
    MEMORY_PURGE_TOMBSTONE_PRESERVED,
    MEMORY_VECTOR_PURGE_ATTEMPTED,
    MEMORY_VECTOR_PURGE_FAILED,
    MEMORY_VECTOR_PURGE_VERIFIED,
    WorkerJob,
    WorkerJobResult,
    WorkerRunStatus,
)
from .vector_purge import verify_purged

_DELETED = "deleted"
_COMPACTION_REASON = "soft-deleted memory past retention window; content + vector material cleared"


class DeletionCompactionWorker(LifecycleWorker):
    job = WorkerJob.deletion_compaction

    def __init__(
        self,
        repo: Repository,
        audit: AuditService | None = None,
        *,
        min_age_days: int | None = None,
    ) -> None:
        super().__init__(repo, audit)
        s = get_settings()
        self._min_age_days = (
            min_age_days if min_age_days is not None else s.workers_compaction_min_age_days
        )

    @staticmethod
    def _deleted_age_days(memory: StoredMemory, now: datetime) -> int:
        ts = memory.deleted_at or memory.updated_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return max(0, (now - ts).days)

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        started = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=DELETION_COMPACTION_STARTED,
            reason="deletion compaction scan started",
            trace_id=ctx.trace_id,
            metadata={"dry_run": ctx.dry_run, "min_age_days": self._min_age_days},
        )
        result.audit_event_ids.append(started.id)

        eligible = compacted = verified = failed = tombstones = 0
        # Repository excludes already-compacted rows → idempotent, retry-safe.
        for memory in self._repo.list_deleted_for_compaction(ctx.tenant_id, ctx.user_id):
            result.scanned_count += 1
            # Defense in depth: only deleted rows, never resurrect/touch active.
            if memory.status.value != _DELETED:
                result.skipped_count += 1
                continue
            if self._deleted_age_days(memory, ctx.now) < self._min_age_days:
                result.skipped_count += 1  # within retention window; not yet eligible
                continue

            eligible += 1
            if ctx.dry_run:
                result.changed_count += 1  # candidate only; nothing cleared
                continue

            row = self._repo.compact_deleted_memory(
                ctx.tenant_id,
                ctx.user_id,
                memory.id,
                reason=_COMPACTION_REASON,
                now=ctx.now,
            )
            if row is None:
                # Lost a race (no longer deleted): skip rather than force.
                result.skipped_count += 1
                continue

            compacted += 1
            result.changed_count += 1
            result.audit_event_ids.append(
                self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=MEMORY_CONTENT_COMPACTED,
                    reason="retrievable content cleared for soft-deleted memory",
                    memory_id=memory.id,
                    trace_id=ctx.trace_id,
                    metadata={"deleted_age_days": self._deleted_age_days(memory, ctx.now)},
                ).id
            )
            result.audit_event_ids.append(
                self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=MEMORY_VECTOR_PURGE_ATTEMPTED,
                    reason="vector material cleared; verifying exclusion",
                    memory_id=memory.id,
                    trace_id=ctx.trace_id,
                ).id
            )

            check = verify_purged(
                self._repo,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                memory_id=memory.id,
            )
            if check.passed:
                verified += 1
                result.audit_event_ids.append(
                    self._audit.record(
                        tenant_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        action=MEMORY_VECTOR_PURGE_VERIFIED,
                        reason="compacted memory unreachable; content + vector cleared",
                        memory_id=memory.id,
                        trace_id=ctx.trace_id,
                        metadata={"verification_result": check.result},
                    ).id
                )
                if check.tombstone_present:
                    tombstones += 1
                    result.audit_event_ids.append(
                        self._audit.record(
                            tenant_id=ctx.tenant_id,
                            user_id=ctx.user_id,
                            action=MEMORY_PURGE_TOMBSTONE_PRESERVED,
                            reason="governance tombstone + audit trail preserved",
                            memory_id=memory.id,
                            trace_id=ctx.trace_id,
                        ).id
                    )
            else:
                failed += 1
                result.error_count += 1
                result.audit_event_ids.append(
                    self._audit.record(
                        tenant_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        action=MEMORY_VECTOR_PURGE_FAILED,
                        reason="purge verification failed (fail-closed)",
                        memory_id=memory.id,
                        trace_id=ctx.trace_id,
                        metadata={
                            "verification_result": check.result,
                            "reachable_surfaces": check.reachable_surfaces,
                            "detail": check.reason,
                        },
                    ).id
                )

        result.details = {
            "deleted_scanned": result.scanned_count,
            "eligible_count": eligible,
            "compacted_count": compacted,
            "verified_count": verified,
            "failed_count": failed,
            "skipped_count": result.skipped_count,
            "tombstone_preserved_count": tombstones,
            "dry_run": ctx.dry_run,
        }

        if eligible == 0:
            result.audit_event_ids.append(
                self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=DELETION_COMPACTION_SKIPPED,
                    reason="no soft-deleted memory eligible for compaction",
                    trace_id=ctx.trace_id,
                    metadata={"scanned": result.scanned_count},
                ).id
            )

        if failed:
            result.status = WorkerRunStatus.completed_with_findings.value
            result.audit_event_ids.append(
                self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=DELETION_COMPACTION_FAILED,
                    reason=f"deletion compaction completed with {failed} purge finding(s)",
                    trace_id=ctx.trace_id,
                    metadata=dict(result.details),
                ).id
            )
        else:
            result.audit_event_ids.append(
                self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=DELETION_COMPACTION_COMPLETED,
                    reason=(
                        f"deletion compaction completed: compacted={compacted} "
                        f"verified={verified}"
                    ),
                    trace_id=ctx.trace_id,
                    metadata=dict(result.details),
                ).id
            )
