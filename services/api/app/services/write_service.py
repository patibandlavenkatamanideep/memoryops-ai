"""Write Service — persists a policy decision and emits the audit event.

Translates a PolicyOutcome into a storage action: SAVE/PENDING create rows,
UPDATE/MERGE reinforce an existing row, BLOCK/DROP store nothing but still audit.
Every path records provenance (invariant #3) and an audit event (invariant #7).
"""

from __future__ import annotations

from ..core.embeddings import embed
from ..core.reliability import safe_call
from ..db.entities import StoredMemory
from ..db.repository import Repository
from ..schemas.memory import CandidateDecision, Decision, Status
from .audit import AuditService
from .policy_broker import PolicyOutcome

# Map a decision to its audit action verb.
_AUDIT_ACTION = {
    Decision.SAVE: "memory_created",
    Decision.PENDING_APPROVAL: "memory_pending_approval",
    Decision.BLOCK: "memory_blocked",
    Decision.DROP_LOW_UTILITY: "memory_dropped",
    Decision.UPDATE_EXISTING: "memory_updated",
    Decision.MERGE_WITH_EXISTING: "memory_merged",
}


class WriteService:
    def __init__(self, repo: Repository, audit: AuditService) -> None:
        self._repo = repo
        self._audit = audit

    def commit(
        self,
        outcome: PolicyOutcome,
        *,
        tenant_id: str,
        user_id: str,
        trace_id: str,
    ) -> tuple[CandidateDecision, list[str]]:
        cand = outcome.candidate
        decision = outcome.decision
        memory_id: str | None = None
        audit_ids: list[str] = []

        # Embedding is a best-effort network call; compute it *before* opening the
        # transaction so we never hold a DB unit of work across it (and so failure,
        # already swallowed by safe_call, can't affect atomicity).
        embedding: list[float] = []
        if decision in (Decision.SAVE, Decision.PENDING_APPROVAL):
            embedding = safe_call(lambda: embed(cand.content), default=[], label="embed")

        # Persist-plus-audit is one atomic unit of work (P0): a crash between the
        # memory mutation and its audit event can no longer leave one without the
        # other. BLOCK/DROP store nothing but still audit inside the same boundary.
        with self._repo.transaction(tenant_id, user_id):
            if decision in (Decision.SAVE, Decision.PENDING_APPROVAL):
                status = Status.active if decision == Decision.SAVE else Status.pending
                stored = StoredMemory(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    memory_type=cand.type,
                    content=cand.content,
                    normalized_content=" ".join(cand.content.lower().split()),
                    embedding=embedding,
                    importance=cand.importance,
                    confidence=cand.confidence,
                    sensitivity=cand.sensitivity,
                    status=status,
                    source=cand.source,
                )
                self._repo.create_memory(stored)
                memory_id = stored.id

            elif decision in (Decision.UPDATE_EXISTING, Decision.MERGE_WITH_EXISTING):
                existing = (
                    self._repo.get_memory(tenant_id, user_id, outcome.existing_id)
                    if outcome.existing_id
                    else None
                )
                if existing:
                    existing.reinforcement_count += 1
                    existing.weight = min(existing.weight + 0.1, 2.0)
                    existing.importance = max(existing.importance, cand.importance)
                    existing.confidence = max(existing.confidence, cand.confidence)
                    self._repo.update_memory(existing)
                    memory_id = existing.id

            event = self._audit.record(
                tenant_id=tenant_id,
                user_id=user_id,
                memory_id=memory_id,
                action=_AUDIT_ACTION[decision],
                reason=outcome.reason,
                trace_id=trace_id,
                metadata={"type": cand.type.value, "sensitivity": cand.sensitivity.value},
            )
            audit_ids.append(event.id)

        decision_view = CandidateDecision(
            content=cand.content,
            decision=decision,
            type=cand.type,
            confidence=cand.confidence,
            importance=cand.importance,
            sensitivity=cand.sensitivity,
            reason=outcome.reason,
            memory_id=memory_id,
        )
        return decision_view, audit_ids
