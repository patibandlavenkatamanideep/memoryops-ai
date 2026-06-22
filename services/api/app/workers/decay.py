"""Decay worker (v0.6).

Finds old or low-confidence *active* memories and reduces their importance toward
a floor, marking them as decayed. This demotes stale memory in ranking without
deleting it — forgetting stays governed and reversible.

Idempotency: each eligible memory is decayed at most once and stamped
``metadata.lifecycle.decayed=True``; a re-run skips already-decayed rows, so the
job is safe to retry and converges. Deleted memory is never selected (the scan
reads active rows only) and is therefore never modified or resurrected.
"""

from __future__ import annotations

from ..core.config import get_settings
from ..db.repository import Repository
from ..services.audit import AuditService
from .lifecycle import LifecycleWorker, WorkerContext, age_days, lifecycle_meta, set_lifecycle_meta
from .schemas import MEMORY_DECAY_APPLIED, WorkerJob, WorkerJobResult


class DecayWorker(LifecycleWorker):
    job = WorkerJob.decay

    def __init__(
        self,
        repo: Repository,
        audit: AuditService | None = None,
        *,
        age_threshold_days: int | None = None,
        min_confidence: float | None = None,
        importance_floor: int | None = None,
        importance_step: int | None = None,
    ) -> None:
        super().__init__(repo, audit)
        s = get_settings()
        self._age_threshold_days = (
            age_threshold_days if age_threshold_days is not None else s.workers_decay_age_days
        )
        self._min_confidence = (
            min_confidence if min_confidence is not None else s.workers_decay_min_confidence
        )
        self._importance_floor = (
            importance_floor if importance_floor is not None else s.workers_decay_importance_floor
        )
        self._importance_step = (
            importance_step if importance_step is not None else s.workers_decay_importance_step
        )

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        for memory in self._active_memories(ctx):
            result.scanned_count += 1
            meta = lifecycle_meta(memory)
            if meta.get("decayed"):
                result.skipped_count += 1  # idempotent: already decayed
                continue

            age = age_days(memory, ctx.now)
            eligible = age >= self._age_threshold_days or memory.confidence < self._min_confidence
            if not eligible:
                result.skipped_count += 1
                continue
            if memory.importance <= self._importance_floor:
                result.skipped_count += 1  # nothing left to reduce
                continue

            old_importance = memory.importance
            new_importance = max(self._importance_floor, old_importance - self._importance_step)
            if ctx.dry_run:
                result.skipped_count += 1
                continue

            memory.importance = new_importance
            set_lifecycle_meta(
                memory,
                {"decayed": True, "decay_age_days": age, "decay_from_importance": old_importance},
            )
            self._repo.update_memory(memory)
            event = self._audit.record(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                action=MEMORY_DECAY_APPLIED,
                reason="importance decayed for aged/low-confidence memory",
                memory_id=memory.id,
                trace_id=ctx.trace_id,
                metadata={
                    "old_importance": old_importance,
                    "new_importance": new_importance,
                    "age_days": age,
                    "low_confidence": memory.confidence < self._min_confidence,
                },
            )
            result.audit_event_ids.append(event.id)
            result.changed_count += 1
