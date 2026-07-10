"""Recall Gate — audience-aware entry into context (v1.9, ADR-023).

The Context Admission Gate (v1.3) decides whether a memory is *allowed* at all
(deleted / expired / consent / tombstone / relevance). The **Recall Gate** adds the
missing dimension: *should this memory be recalled for **this** session/audience?* A
high-sensitivity memory that is perfectly admissible for a private session must not be
recalled into a shared/public one.

It runs after admission / before composition, consumes the already-admitted records,
and re-blocks any whose sensitivity exceeds the audience's clearance — reusing the
`AdmissionRecord` shape (decision `BLOCK_AUDIENCE`) so the existing Memory Usage Trace,
metrics, and audit machinery explain it for free. Defense-in-depth: it only ever
*removes* memory, never adds (invariants #1/#2 stay intact).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..schemas.memory import Sensitivity
from .admission_gate import AdmissionDecision, AdmissionRecord

# Which sensitivities each audience is cleared to recall.
_CLEARANCE: dict[str, set[Sensitivity]] = {
    "private": {Sensitivity.low, Sensitivity.medium, Sensitivity.high},
    "team": {Sensitivity.low, Sensitivity.medium},
    "public": {Sensitivity.low},
}


@dataclass
class RecallResult:
    allowed: list[AdmissionRecord]
    blocked: list[AdmissionRecord]  # newly blocked by audience clearance

    @property
    def admitted_ranked(self):
        return [r.ranked for r in self.allowed]


class RecallGate:
    def evaluate(self, admitted: list[AdmissionRecord], *, audience: str) -> RecallResult:
        cleared = _CLEARANCE.get(audience, _CLEARANCE["private"])
        allowed: list[AdmissionRecord] = []
        blocked: list[AdmissionRecord] = []
        for record in admitted:
            if record.memory.sensitivity in cleared:
                allowed.append(record)
            else:
                blocked.append(
                    replace(
                        record,
                        decision=AdmissionDecision.BLOCK_AUDIENCE,
                        reason=(
                            f"sensitivity '{record.memory.sensitivity.value}' exceeds "
                            f"'{audience}' audience clearance"
                        ),
                    )
                )
        return RecallResult(allowed=allowed, blocked=blocked)
