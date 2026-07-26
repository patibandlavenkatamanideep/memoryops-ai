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
            outcome = decision.outcome

            # A `repo.transaction(...)` is opened only around a real mutation +
            # audit *pair* (invariant #7, ADR-027) — never around a preview
            # (audit-only) decision or a lone window stamp with no paired audit, so a
            # normal scan does not pay a per-item store snapshot on the in-memory
            # backend. When wrapped, the transaction is opened before
            # `gov.set_retention` mutates the memory in place so an in-memory rollback
            # undoes it (see LifecycleWorker._atomic). Counters stay outside the
            # transaction (a rollback fails the whole run anyway).

            # ── held: preserved, never deleted ──────────────────────────────────
            if outcome is RetentionOutcome.held:
                held += 1
                result.skipped_count += 1
                if preview_only:
                    self._stamp_window(memory, decision, ctx)
                    self._record_decision(ctx, result, decision, MEMORY_RETENTION_HOLD_RESPECTED)
                else:
                    with self._atomic(ctx):  # decision audit + persisted stamp
                        self._stamp_window(memory, decision, ctx)
                        self._record_decision(
                            ctx, result, decision, MEMORY_RETENTION_HOLD_RESPECTED
                        )
                        self._repo.update_memory(memory)
                continue

            # ── not eligible: stamp the window (lone write, no paired audit) ─────
            if not decision.eligible_for_deletion:
                result.skipped_count += 1
                self._stamp_window(memory, decision, ctx)
                if not preview_only:
                    self._repo.update_memory(memory)  # no audit to pair → no txn
                continue

            # ── eligible: expired window or revoked consent ─────────────────────
            if outcome is RetentionOutcome.expired:
                expired += 1
            else:
                consent_revoked += 1

            if preview_only:
                self._stamp_window(memory, decision, ctx)
                self._record_decision(ctx, result, decision, _OUTCOME_ACTION[outcome])
                result.changed_count += 1  # candidate only; nothing deleted
                continue

            # Real deletion: decision/outcome audit + soft-delete commit together.
            row = None
            with self._atomic(ctx):
                self._stamp_window(memory, decision, ctx)
                self._record_decision(ctx, result, decision, _OUTCOME_ACTION[outcome])
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

    def _stamp_window(self, memory, decision, ctx) -> None:
        """Stamp the computed retention window on the memory (in place) so the API/
        admin can read it without re-evaluating. When persisted, this must happen
        inside the same transaction as the paired audit (opened before this call)."""
        gov.set_retention(
            memory, policy=self._policy.name,
            expires_at=decision.retention_expires_at, now=ctx.now,
        )

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
