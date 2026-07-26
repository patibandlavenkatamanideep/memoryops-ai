"""Retention worker (v0.10, ADR-013).

Evaluates *active* memory against a retention policy pack and soft-deletes the
memory whose retention window has elapsed or whose consent was withdrawn/expired
— **unless** it is on legal hold, pinned, or protected, which override and block
all forgetting. The worker only ever soft-deletes (``status='deleted'``); the
existing deletion-verification and deletion-compaction workers then handle the
deleted rows. Every decision is recorded as content-free, admin-readable audit
evidence.

Safety rails:
  * legal hold / pin / protection are honored absolutely — held memory is never
    deleted and the override is recorded (``memory_retention_hold_respected``);
  * only *active* rows are scanned (deletion guarantee preserved — deleted memory
    is never touched or resurrected, invariant #2);
  * tenant + user scoped through the repository (invariant #1);
  * idempotent — once a memory is soft-deleted it leaves the active set, so a
    re-run neither re-deletes nor double-counts it;
  * ``dry_run`` records decisions and counts candidates but deletes nothing;
  * OFF by default (``workers_retention_enabled``) so an unconfigured run never
    auto-deletes — it still records decisions so operators can preview impact.

The retention engine decides eligibility; the policy broker stays authoritative
and is never bypassed (invariant #5). See docs/retention-policies.md.
"""

from __future__ import annotations

from ..core.config import get_settings
from ..db import governance as gov
from ..db.repository import Repository
from ..services.audit import AuditService
from ..services.retention import RetentionOutcome, get_policy
from .lifecycle import LifecycleWorker, WorkerContext
from .schemas import (
    MEMORY_CONSENT_REVOKED,
    MEMORY_RETENTION_EXPIRED,
    MEMORY_RETENTION_HOLD_RESPECTED,
    RETENTION_DECISION_RECORDED,
    RETENTION_SCAN_COMPLETED,
    RETENTION_SCAN_STARTED,
    WorkerJob,
    WorkerJobResult,
)

_OUTCOME_ACTION = {
    RetentionOutcome.expired: MEMORY_RETENTION_EXPIRED,
    RetentionOutcome.consent_revoked: MEMORY_CONSENT_REVOKED,
}


class RetentionWorker(LifecycleWorker):
    job = WorkerJob.retention

    def __init__(
        self,
        repo: Repository,
        audit: AuditService | None = None,
        *,
        enabled: bool | None = None,
        policy_name: str | None = None,
    ) -> None:
        super().__init__(repo, audit)
        s = get_settings()
        self._enabled = enabled if enabled is not None else s.workers_retention_enabled
        self._policy = get_policy(policy_name or s.retention_default_policy)

    def _execute(self, ctx: WorkerContext, result: WorkerJobResult) -> None:
        started = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=RETENTION_SCAN_STARTED,
            reason=f"retention scan started under policy '{self._policy.name}'",
            trace_id=ctx.trace_id,
            metadata={
                "policy": self._policy.name,
                "enabled": self._enabled,
                "dry_run": ctx.dry_run,
            },
        )
        result.audit_event_ids.append(started.id)

        from ..services.retention import evaluate  # local import keeps module load light

        # When the worker is disabled, it still evaluates + records decisions so
        # operators can preview impact, but it deletes nothing (a forced dry run).
        preview_only = ctx.dry_run or not self._enabled
        expired = consent_revoked = held = deleted = 0
        for memory in self._active_memories(ctx):
            result.scanned_count += 1
            decision = evaluate(memory, now=ctx.now, policy=self._policy)

            # Each item's decision/outcome audit and its persistence (stamped window
            # or soft-delete) commit together (invariant #7, ADR-027). The transaction
            # is opened before `gov.set_retention` mutates the memory in place, so an
            # in-memory rollback undoes it (see LifecycleWorker._atomic).
            with self._atomic(ctx):
                # Stamp the computed window so the API/admin can read it without
                # re-evaluating.
                gov.set_retention(
                    memory, policy=self._policy.name,
                    expires_at=decision.retention_expires_at, now=ctx.now,
                )

                if decision.outcome is RetentionOutcome.held:
                    held += 1
                    result.skipped_count += 1
                    self._record_decision(ctx, result, decision, MEMORY_RETENTION_HOLD_RESPECTED)
                    if not preview_only:
                        self._repo.update_memory(memory)
                    continue

                if not decision.eligible_for_deletion:
                    result.skipped_count += 1
                    if not preview_only:
                        self._repo.update_memory(memory)  # persist stamped window
                    continue

                # Eligible: expired window or revoked consent.
                if decision.outcome is RetentionOutcome.expired:
                    expired += 1
                else:
                    consent_revoked += 1

                self._record_decision(ctx, result, decision, _OUTCOME_ACTION[decision.outcome])

                if preview_only:
                    result.changed_count += 1  # candidate only; nothing deleted
                    continue

                row = self._repo.soft_delete(ctx.tenant_id, ctx.user_id, memory.id)
                if row is None:
                    result.skipped_count += 1
                    continue
                deleted += 1
                result.changed_count += 1

        result.details = {
            "policy": self._policy.name,
            "enabled": self._enabled,
            "scanned_count": result.scanned_count,
            "expired_count": expired,
            "consent_revoked_count": consent_revoked,
            "held_count": held,
            "deleted_count": deleted,
            "dry_run": ctx.dry_run,
        }
        completed = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=RETENTION_SCAN_COMPLETED,
            reason=(
                f"retention scan completed: expired={expired} "
                f"consent_revoked={consent_revoked} held={held} deleted={deleted}"
            ),
            trace_id=ctx.trace_id,
            metadata=dict(result.details),
        )
        result.audit_event_ids.append(completed.id)

    def _record_decision(self, ctx, result, decision, action) -> None:
        """Emit the admin-readable retention decision + the outcome event."""
        decision_event = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=RETENTION_DECISION_RECORDED,
            reason=decision.reason,
            memory_id=decision.memory_id,
            trace_id=ctx.trace_id,
            metadata=decision.to_dict(),
        )
        result.audit_event_ids.append(decision_event.id)
        outcome_event = self._audit.record(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            action=action,
            reason=decision.reason,
            memory_id=decision.memory_id,
            trace_id=ctx.trace_id,
            metadata={
                "policy": decision.policy,
                "outcome": decision.outcome.value,
                "blocked_by": decision.blocked_by,
                "dry_run": ctx.dry_run,
            },
        )
        result.audit_event_ids.append(outcome_event.id)
