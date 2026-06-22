"""Reflection / summarization worker (v0.6) — minimal, safe, off by default.

Reflection (consolidating clusters of low-level memories into a higher-level
summary) is powerful but risky: done wrong it can fabricate memory, drop
provenance, or — worst of all — delete the source memories it summarized. To stay
safe and minimal in v0.6 this worker is **proposal-only and disabled by default**:

  * it groups *active, low-importance* memory by type within the ctx scope;
  * for clusters at/above ``min_cluster_size`` it emits a
    ``reflection_candidate_detected`` review candidate that records the source
    memory ids (provenance) and a content-free summary descriptor;
  * it never writes a new memory, never mutates, and never deletes a source.

Actually authoring a consolidated memory is deferred to a later milestone and must
go through the policy broker (it would land as ``pending`` for governance review,
with ``source.kind='reflection'`` linking the source ids). Enable proposals with
``MEMORYOPS_WORKERS_REFLECTION=1``. See ADR-010 / docs/background-lifecycle-workers.md.
"""

from __future__ import annotations

from collections import defaultdict

from ..core.config import get_settings
from ..db.repository import Repository
from ..services.audit import AuditService
from .lifecycle import LifecycleWorker, WorkerContext
from .schemas import (
    REFLECTION_CANDIDATE_DETECTED,
    WorkerJob,
    WorkerJobResult,
    WorkerRunStatus,
)


class ReflectionWorker(LifecycleWorker):
    job = WorkerJob.reflection

    def __init__(
        self,
        repo: Repository,
        audit: AuditService | None = None,
        *,
        enabled: bool | None = None,
        min_cluster_size: int | None = None,
        max_importance: int | None = None,
    ) -> None:
        super().__init__(repo, audit)
        s = get_settings()
        self._enabled = enabled if enabled is not None else s.workers_reflection_enabled
        self._min_cluster_size = (
            min_cluster_size
            if min_cluster_size is not None
            else s.workers_reflection_min_cluster_size
        )
        self._max_importance = (
            max_importance if max_importance is not None else s.workers_reflection_max_importance
        )

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        if not self._enabled:
            result.status = WorkerRunStatus.skipped.value
            result.details = {"reason": "reflection_disabled"}
            return

        clusters: dict[str, list[str]] = defaultdict(list)
        for memory in self._active_memories(ctx):
            result.scanned_count += 1
            if memory.importance <= self._max_importance:
                clusters[memory.memory_type.value].append(memory.id)

        for memory_type, ids in clusters.items():
            if len(ids) < self._min_cluster_size:
                result.skipped_count += 1
                continue
            event = self._audit.record(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                action=REFLECTION_CANDIDATE_DETECTED,
                reason=(
                    f"{len(ids)} low-importance '{memory_type}' memories eligible "
                    "for consolidation (review candidate; no memory written)"
                ),
                trace_id=ctx.trace_id,
                metadata={
                    "memory_type": memory_type,
                    "source_memory_ids": ids,
                    "cluster_size": len(ids),
                },
            )
            result.audit_event_ids.append(event.id)
            result.changed_count += 1  # a review candidate was produced
