"""Context Admission Gate — permissioned entry into context (v1.3, ADR-017).

Normal RAG asks "is this memory *relevant*?". MemoryOps also asks "is this memory
*allowed* into context for this turn?". This gate runs **after** the ranker and
**before** the context composer:

    retrieve → rank → [ADMISSION GATE] → compose → LLM

For each ranked candidate it returns an explainable verdict — ``ALLOW`` or a
specific ``BLOCK_*`` — and only ``ALLOW`` memories reach the composer. The gate is
**defense-in-depth**: it only ever *removes* memory from context, never adds. That
keeps it aligned with the invariants — tenant isolation (#1), the deletion
guarantee (#2), and graceful degradation (#4, it never blocks the *response*, only
context admission). Every turn's blocked verdicts are audited (#7) by the caller.

Governance state (consent, retention window, legal hold / pin / protect) is read
through ``app/db/governance.py`` — this module never hand-rolls metadata keys.

Conservative defaults preserve behavior: the repository already filters non-active
rows, so ``BLOCK_DELETED``/``BLOCK_ARCHIVED``/``BLOCK_WRONG_TENANT`` are pure
belt-and-suspenders; ``BLOCK_EXPIRED``/``BLOCK_CONSENT_WITHDRAWN`` catch *active*
memory whose governance turned against admission before a worker removed it. The
two stricter gates (``BLOCK_SENSITIVE``, ``BLOCK_LOW_CONFIDENCE``) are opt-in.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from ..core.config import get_settings
from ..db import governance as gov
from ..db import lineage
from ..db.entities import StoredMemory
from ..schemas.memory import (
    MemoryTraceEntry,
    Sensitivity,
    Status,
)
from .ranker import RankedMemory

# Resolves a memory id to its stored row (must return soft-deleted rows too) so
# the gate can walk lineage ancestry. Supplied by the gateway (has the repo).
AncestorLookup = Callable[[str], "StoredMemory | None"]

_PREVIEW_CHARS = 160


class AdmissionDecision(str, Enum):
    ALLOW = "ALLOW"
    BLOCK_WRONG_TENANT = "BLOCK_WRONG_TENANT"
    BLOCK_DELETED = "BLOCK_DELETED"
    BLOCK_ARCHIVED = "BLOCK_ARCHIVED"
    BLOCK_INACTIVE = "BLOCK_INACTIVE"  # pending / rejected / blocked
    BLOCK_CONSENT_WITHDRAWN = "BLOCK_CONSENT_WITHDRAWN"
    BLOCK_EXPIRED = "BLOCK_EXPIRED"  # retention window elapsed
    BLOCK_TOMBSTONED_ANCESTOR = "BLOCK_TOMBSTONED_ANCESTOR"  # derived from deleted memory
    BLOCK_SENSITIVE = "BLOCK_SENSITIVE"  # opt-in
    BLOCK_LOW_CONFIDENCE = "BLOCK_LOW_CONFIDENCE"  # opt-in
    BLOCK_AUDIENCE = "BLOCK_AUDIENCE"  # recall gate: sensitivity exceeds audience clearance (v1.9)


@dataclass
class AdmissionRecord:
    """One memory's admission verdict plus the governance snapshot behind it."""

    ranked: RankedMemory
    decision: AdmissionDecision
    reason: str
    consent_status: str
    retention_status: str  # active | expired | exempt | none

    @property
    def memory(self):
        return self.ranked.memory

    @property
    def allowed(self) -> bool:
        return self.decision is AdmissionDecision.ALLOW

    def to_trace_entry(self) -> MemoryTraceEntry:
        m = self.memory
        content = m.content or ""
        preview = content[:_PREVIEW_CHARS] + ("…" if len(content) > _PREVIEW_CHARS else "")
        return MemoryTraceEntry(
            memory_id=m.id,
            memory_type=m.memory_type,
            content_preview=preview,
            source=m.source,
            stored_at=m.created_at,
            status=m.status,
            sensitivity=m.sensitivity,
            consent_status=self.consent_status,
            retention_status=self.retention_status,
            admission_decision=self.decision.value,
            admission_reason=self.reason,
            retrieval_score=self.ranked.score,
            score_breakdown=self.ranked.score_breakdown,
        )


@dataclass
class AdmissionResult:
    """Every candidate's verdict, in ranked order, plus the admitted subset."""

    records: list[AdmissionRecord]
    enforced: bool  # False = observe-only (shadow) mode

    @property
    def admitted_records(self) -> list[AdmissionRecord]:
        # In observe-only (shadow) mode nothing is removed; verdicts are still
        # recorded so the trace shows what *would* have been blocked.
        if not self.enforced:
            return list(self.records)
        return [r for r in self.records if r.allowed]

    @property
    def blocked_records(self) -> list[AdmissionRecord]:
        if not self.enforced:
            return []
        return [r for r in self.records if not r.allowed]

    @property
    def admitted(self) -> list[RankedMemory]:
        """The candidates that reach the context composer."""
        return [r.ranked for r in self.admitted_records]

    def counts(self) -> dict[str, int]:
        return dict(Counter(r.decision.value for r in self.records))


class AdmissionGate:
    def evaluate(
        self,
        ranked: list[RankedMemory],
        *,
        tenant_id: str,
        user_id: str,
        now: datetime | None = None,
        ancestor_lookup: AncestorLookup | None = None,
    ) -> AdmissionResult:
        now = now or datetime.now(UTC)
        settings = get_settings()
        records = [
            self._decide(
                r,
                tenant_id=tenant_id,
                user_id=user_id,
                now=now,
                settings=settings,
                ancestor_lookup=ancestor_lookup,
            )
            for r in ranked
        ]
        return AdmissionResult(records=records, enforced=settings.admission_gate_enabled)

    def _decide(
        self,
        ranked: RankedMemory,
        *,
        tenant_id: str,
        user_id: str,
        now: datetime,
        settings,
        ancestor_lookup: AncestorLookup | None = None,
    ) -> AdmissionRecord:
        m = ranked.memory
        consent = gov.consent_status(m, now=now)
        retention = self._retention_status(m, now=now)

        def rec(decision: AdmissionDecision, reason: str) -> AdmissionRecord:
            return AdmissionRecord(
                ranked=ranked,
                decision=decision,
                reason=reason,
                consent_status=consent,
                retention_status=retention,
            )

        # 1. Tenant/user scope (defense-in-depth; repository already filters).
        if m.tenant_id != tenant_id or m.user_id != user_id:
            return rec(AdmissionDecision.BLOCK_WRONG_TENANT, "memory is out of tenant/user scope")

        # 2. Status — deleted memory can never be retrieved (invariant #2).
        if m.status is Status.deleted:
            return rec(AdmissionDecision.BLOCK_DELETED, "memory is deleted")
        if m.status is Status.archived:
            return rec(AdmissionDecision.BLOCK_ARCHIVED, "memory is archived")
        if m.status is not Status.active:
            return rec(
                AdmissionDecision.BLOCK_INACTIVE, f"memory status is '{m.status.value}', not active"
            )

        # 3. Consent — a withdrawn/expired grant denies admission even while the
        #    row is still active (the retention worker deletes it later).
        if consent in gov.ConsentStatus.REVOKED:
            return rec(
                AdmissionDecision.BLOCK_CONSENT_WITHDRAWN,
                f"consent is '{consent}'",
            )

        # 4. Retention window elapsed → block, unless a hold/pin/protect exempts it.
        if retention == "expired":
            return rec(
                AdmissionDecision.BLOCK_EXPIRED,
                "retention window has elapsed",
            )

        # 5. Tombstone lineage (v1.4): a derived artifact may not enter context if
        #    any ancestor is tombstoned (deleted / purged / marked). This is how
        #    the deletion guarantee (#2) propagates to summaries/consolidations.
        if ancestor_lookup is not None and lineage.is_derived(m):
            tombstoned = lineage.ancestry_tombstone(m, ancestor_lookup)
            if tombstoned is not None:
                return rec(
                    AdmissionDecision.BLOCK_TOMBSTONED_ANCESTOR,
                    f"derived from a tombstoned/deleted ancestor ({tombstoned})",
                )

        # 6. Sensitivity gate (opt-in; off by default).
        if settings.admission_block_sensitive and m.sensitivity is Sensitivity.high:
            return rec(
                AdmissionDecision.BLOCK_SENSITIVE,
                "sensitivity is 'high' and the sensitivity gate is enabled",
            )

        # 7. Low-confidence gate (opt-in; min_score=0 disables it).
        if settings.admission_min_score > 0 and ranked.score < settings.admission_min_score:
            return rec(
                AdmissionDecision.BLOCK_LOW_CONFIDENCE,
                f"ranked score {ranked.score} is below the admission threshold "
                f"{settings.admission_min_score}",
            )

        exempt = " (retention-exempt)" if retention == "exempt" else ""
        return rec(
            AdmissionDecision.ALLOW,
            f"relevant, active, consent-{consent}, tenant-scoped{exempt}",
        )

    @staticmethod
    def _retention_status(memory, *, now: datetime) -> str:
        """active | expired | exempt | none — the retention posture for the trace."""
        if gov.is_retention_exempt(memory):
            return "exempt"
        state = gov.retention_state(memory)
        expires_at = _parse_dt(state.get("expires_at")) if state else None
        if expires_at is None:
            return "none"
        return "expired" if now >= expires_at else "active"


def _parse_dt(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
