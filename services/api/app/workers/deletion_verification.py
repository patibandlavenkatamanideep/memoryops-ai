"""Deletion verification worker (v0.6).

A *verification* job — it reads, never mutates. For every soft-deleted memory in
scope it confirms the deletion guarantee (invariant #2) still holds at the access
paths a caller could reach:

  * active retrieval (``retrieve_active``),
  * default memory listing (``list_memories`` excludes deleted),
  * the vector candidate path (``search_candidates``).

If a deleted id is absent from all three it passes; if one ever leaks, it records
``deletion_verification_failed`` evidence (and the run is flagged with findings)
so the leak is caught without the worker itself touching data.

Scope of this worker: **logical** deletion verification. Physical/vector purge
(compaction, crypto-shred) is intentionally out of scope and staged as future
work — see docs/deletion-verification.md.
"""

from __future__ import annotations

from ..db.repository import Repository
from ..services.audit import AuditService
from .lifecycle import LifecycleWorker, WorkerContext
from .schemas import (
    DELETION_VERIFICATION_FAILED,
    DELETION_VERIFICATION_PASSED,
    WorkerJob,
    WorkerJobResult,
    WorkerRunStatus,
)

_DELETED = "deleted"


class DeletionVerificationWorker(LifecycleWorker):
    job = WorkerJob.deletion_verification

    def __init__(self, repo: Repository, audit: AuditService | None = None) -> None:
        super().__init__(repo, audit)

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        deleted = [
            m
            for m in self._repo.list_memories(
                ctx.tenant_id, ctx.user_id, status=_DELETED, include_deleted=True
            )
            if m.status.value == _DELETED
        ]

        # The three reachable read surfaces. An empty embedding makes the vector
        # path degrade to "active rows at similarity 0", which is exactly the set
        # we must confirm a deleted id never appears in.
        active_ids = {m.id for m in self._repo.retrieve_active(ctx.tenant_id, ctx.user_id)}
        listed_ids = {m.id for m in self._repo.list_memories(ctx.tenant_id, ctx.user_id)}
        candidate_ids = {
            m.id for m, _ in self._repo.search_candidates(ctx.tenant_id, ctx.user_id, [])
        }
        reachable = active_ids | listed_ids | candidate_ids

        leaked: list[str] = []
        for memory in deleted:
            result.scanned_count += 1
            if memory.id in reachable:
                leaked.append(memory.id)
                surfaces = [
                    name
                    for name, ids in (
                        ("active_retrieval", active_ids),
                        ("listing", listed_ids),
                        ("vector_candidates", candidate_ids),
                    )
                    if memory.id in ids
                ]
                event = self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=DELETION_VERIFICATION_FAILED,
                    reason="deleted memory reachable in a retrieval surface",
                    memory_id=memory.id,
                    trace_id=ctx.trace_id,
                    metadata={"surfaces": surfaces},
                )
                result.audit_event_ids.append(event.id)
                result.error_count += 1

        result.details = {
            "deleted_count": len(deleted),
            "leaked_count": len(leaked),
            "verified_count": len(deleted) - len(leaked),
        }

        if leaked:
            result.status = WorkerRunStatus.completed_with_findings.value
        else:
            event = self._audit.record(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                action=DELETION_VERIFICATION_PASSED,
                reason=f"verified {len(deleted)} deleted memory(ies) excluded from retrieval",
                trace_id=ctx.trace_id,
                metadata={"deleted_count": len(deleted)},
            )
            result.audit_event_ids.append(event.id)
