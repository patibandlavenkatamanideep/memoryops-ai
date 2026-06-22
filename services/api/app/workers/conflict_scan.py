"""Conflict scan worker (v0.6).

Scans active memory in scope for likely contradictions and produces *review
candidates* — it never overwrites, merges, or deletes. It reuses the v0.4
advisory conflict detection (``app.llm.detect_conflicts``), which degrades to a
deterministic heuristic with no API key (invariant #4). The policy broker /
human review remain authoritative over what happens to a flagged pair.

Tenant safety: candidates are drawn only from ``retrieve_active`` for the ctx
scope, so a memory is only ever compared against the same tenant/user's memory.
Audit metadata carries memory ids and relation labels only — never raw content.
"""

from __future__ import annotations

from ..core.config import get_settings
from ..core.reliability import safe_call
from ..db.repository import Repository
from ..llm import detect_conflicts, get_llm_provider
from ..llm.base import LLMProvider
from ..services.audit import AuditService
from .lifecycle import LifecycleWorker, WorkerContext
from .schemas import CONFLICT_CANDIDATE_DETECTED, WorkerJob, WorkerJobResult


class ConflictScanWorker(LifecycleWorker):
    job = WorkerJob.conflict_scan

    def __init__(
        self,
        repo: Repository,
        audit: AuditService | None = None,
        *,
        provider: LLMProvider | None = None,
        max_memories: int | None = None,
    ) -> None:
        super().__init__(repo, audit)
        self._provider = provider or get_llm_provider()
        s = get_settings()
        self._max_memories = (
            max_memories if max_memories is not None else s.workers_conflict_scan_max_memories
        )

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        active = self._repo.retrieve_active(ctx.tenant_id, ctx.user_id)[: self._max_memories]
        pairs = [(m.id, m.content) for m in active]

        for memory in active:
            result.scanned_count += 1
            others = [(mid, content) for mid, content in pairs if mid != memory.id]
            if not others:
                result.skipped_count += 1
                continue
            outcome = safe_call(
                lambda m=memory, o=others: detect_conflicts(self._provider, m.content, o),
                default=None,
                label="conflict_scan",
            )
            if outcome is None or not outcome.result.has_conflict:
                result.skipped_count += 1
                continue

            conflict_ids = [
                c.existing_memory_id for c in outcome.result.conflicts if c.existing_memory_id
            ]
            relations = sorted({c.relation for c in outcome.result.conflicts})
            event = self._audit.record(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                action=CONFLICT_CANDIDATE_DETECTED,
                reason="potential memory conflict flagged for review (no change made)",
                memory_id=memory.id,
                trace_id=ctx.trace_id,
                metadata={
                    "conflict_with": conflict_ids,
                    "relations": relations,
                    "detection_mode": outcome.mode,
                },
            )
            result.audit_event_ids.append(event.id)
            result.changed_count += 1  # a review candidate was produced
