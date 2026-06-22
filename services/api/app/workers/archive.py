"""Archive worker (v0.6).

Archives stale *active* memory per policy: old enough, not recently used, and not
pinned/protected. Archiving sets ``status='archived'`` (kept out of active
retrieval but recoverable) — it is not deletion.

Safety rails:
  * recently-used memory is skipped (``metadata.lifecycle.last_used_at`` if
    present, else falls back to ``created_at`` — never ``updated_at``, so an
    earlier decay pass can't make a memory look "recently used");
  * pinned/protected memory (``metadata.pinned`` / ``metadata.protected``) is
    never archived;
  * deleted memory is never selected, so it is never touched or resurrected.

Idempotency: once a row is archived it leaves the active set, so a re-run neither
re-archives nor double-counts it. ``dry_run`` emits ``memory_archive_candidate``
without mutating; a real run archives and emits ``memory_archived_by_worker``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..core.config import get_settings
from ..db.entities import StoredMemory
from ..db.repository import Repository
from ..schemas.memory import Status
from ..services.audit import AuditService
from .lifecycle import LifecycleWorker, WorkerContext, age_days, lifecycle_meta, set_lifecycle_meta
from .schemas import (
    MEMORY_ARCHIVE_CANDIDATE,
    MEMORY_ARCHIVED_BY_WORKER,
    WorkerJob,
    WorkerJobResult,
)

_PROTECTED_FLAGS = ("pinned", "protected")


class ArchiveWorker(LifecycleWorker):
    job = WorkerJob.archive

    def __init__(
        self,
        repo: Repository,
        audit: AuditService | None = None,
        *,
        age_threshold_days: int | None = None,
        recent_use_days: int | None = None,
    ) -> None:
        super().__init__(repo, audit)
        s = get_settings()
        self._age_threshold_days = (
            age_threshold_days if age_threshold_days is not None else s.workers_archive_age_days
        )
        self._recent_use_days = (
            recent_use_days if recent_use_days is not None else s.workers_archive_recent_use_days
        )

    @staticmethod
    def _is_protected(memory: StoredMemory) -> bool:
        return any(bool(memory.metadata.get(flag)) for flag in _PROTECTED_FLAGS)

    def _recently_used(self, memory: StoredMemory, now: datetime) -> bool:
        meta = lifecycle_meta(memory)
        raw = meta.get("last_used_at")
        last_used = memory.created_at
        if isinstance(raw, str):
            try:
                last_used = datetime.fromisoformat(raw)
            except ValueError:
                last_used = memory.created_at
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=UTC)
        return (now - last_used).days < self._recent_use_days

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        for memory in self._active_memories(ctx):
            result.scanned_count += 1
            if self._is_protected(memory):
                result.skipped_count += 1
                continue
            if age_days(memory, ctx.now) < self._age_threshold_days:
                result.skipped_count += 1
                continue
            if self._recently_used(memory, ctx.now):
                result.skipped_count += 1
                continue

            if ctx.dry_run:
                event = self._audit.record(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    action=MEMORY_ARCHIVE_CANDIDATE,
                    reason="memory eligible for archival (dry run)",
                    memory_id=memory.id,
                    trace_id=ctx.trace_id,
                    metadata={"age_days": age_days(memory, ctx.now)},
                )
                result.audit_event_ids.append(event.id)
                result.changed_count += 1  # candidate proposed
                continue

            memory.status = Status.archived
            memory.archived_at = ctx.now
            set_lifecycle_meta(memory, {"archived_by_worker": True})
            self._repo.update_memory(memory)
            event = self._audit.record(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                action=MEMORY_ARCHIVED_BY_WORKER,
                reason="stale memory archived by lifecycle worker",
                memory_id=memory.id,
                trace_id=ctx.trace_id,
                metadata={"age_days": age_days(memory, ctx.now)},
            )
            result.audit_event_ids.append(event.id)
            result.changed_count += 1
