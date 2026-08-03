"""Policy Broker / Evaluator — the choke point before storage (ADR-003).

Runs deterministic safety rules first (secrets → BLOCK, injection → BLOCK),
then sensitivity/approval logic, then utility/dedup. Returns a decision plus the
final scored candidate. Nothing reaches the Write Service without a decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import get_settings as get_app_settings
from ..core.redaction import scan
from ..core.sensitivity import BLOCK, is_memory_control_instruction
from ..db.entities import StoredSettings
from ..db.repository import Repository
from ..schemas.memory import CandidateMemory, Decision, Sensitivity


@dataclass
class PolicyOutcome:
    decision: Decision
    candidate: CandidateMemory
    reason: str
    existing_id: str | None = None
    #: Stable machine-readable reason, additive alongside the human `reason`.
    #: `memory_control_instruction` distinguishes "this was never a memory" from a
    #: genuine low-utility drop — reusing DROP_LOW_UTILITY for both would
    #: contaminate utility metrics and error analysis. A dedicated Decision value
    #: (IGNORE_MEMORY_CONTROL / DROP_NOT_MEMORY) is the right long-term shape and is
    #: tracked separately; this keeps the vocabulary additive for now.
    reason_code: str | None = None


# Below this importance an inferred memory is noise.
_MIN_IMPORTANCE = 4

#: Reason code for a memory-control instruction. Metrics over low-utility drops must
#: exclude this: "not a memory at all" and "a valid memory of low utility" are
#: different outcomes, and conflating them skews utility analysis.
REASON_MEMORY_CONTROL = "memory_control_instruction"
REASON_LOW_UTILITY = "low_utility"


class PolicyBroker:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    def evaluate(
        self,
        candidate: CandidateMemory,
        *,
        tenant_id: str,
        user_id: str,
        settings: StoredSettings,
    ) -> PolicyOutcome:
        # Ablation / S0-U (paper study): "enforcement" = the governance *decisions*
        # (secret/injection BLOCK, sensitive-content approval gating). With enforcement
        # disabled those are skipped, but memory *hygiene* — sensitivity labelling,
        # dedup/update-existing, and the low-utility floor — is KEPT, so S0-U stays a
        # fair, mechanism-matched ungoverned twin (disabling dedup too would let S0-U
        # accumulate duplicates and bias H2 utility toward the governed system). Frozen
        # default (`govern_policy_enforcement=True`) enforces exactly as before.
        enforce = get_app_settings().govern_policy_enforcement
        scan_result = scan(candidate.content)

        # 1) Hard safety rules (deterministic, verifiable) — governance enforcement.
        # A memory-control instruction ("do not remember my password") is not a fact.
        # The extractor already declines to emit a candidate for it; this is the
        # independent second guard, so a malformed or LLM-provided extractor that
        # emits one anyway still cannot store it. DROP, not BLOCK: there was never a
        # candidate here worth recording as a refusal.
        if is_memory_control_instruction(candidate.content):
            return PolicyOutcome(
                Decision.DROP_LOW_UTILITY,
                candidate,
                "dropped: memory-control instruction, not a fact to store",
                reason_code=REASON_MEMORY_CONTROL,
            )
        if enforce and scan_result.has_secret:
            return PolicyOutcome(
                Decision.BLOCK,
                candidate,
                f"blocked: secret-like content detected ({', '.join(scan_result.secret_labels)})",
            )
        if enforce and scan_result.assessment.recommended_disposition == BLOCK:
            # A disclosed credential the structural patterns cannot see — e.g.
            # "my password is …", which has no key-like shape.
            return PolicyOutcome(
                Decision.BLOCK,
                candidate,
                "blocked: disclosed credential or identifier "
                f"({', '.join(scan_result.assessment.categories)})",
            )
        if enforce and scan_result.injection:
            return PolicyOutcome(
                Decision.BLOCK,
                candidate,
                "blocked: prompt-injection / memory-poisoning pattern detected",
            )

        # 2) Sensitivity (PII elevates; may require approval). Labelling — kept.
        final_sensitivity = max(
            candidate.sensitivity,
            Sensitivity(scan_result.sensitivity),
            key=_sensitivity_rank,
        )
        candidate = candidate.model_copy(update={"sensitivity": final_sensitivity})

        # 3) Dedup / update existing.
        existing = self._repo.find_similar_active(tenant_id, user_id, candidate.content)
        if existing is not None:
            return PolicyOutcome(
                Decision.UPDATE_EXISTING,
                candidate,
                "reinforces an existing memory; updating instead of duplicating",
                existing_id=existing.id,
            )

        # 4) Low-utility drop.
        if candidate.importance < _MIN_IMPORTANCE:
            return PolicyOutcome(
                Decision.DROP_LOW_UTILITY,
                candidate,
                f"dropped: importance {candidate.importance} below threshold {_MIN_IMPORTANCE}",
                reason_code=REASON_LOW_UTILITY,
            )

        # 5) Sensitive content gated behind approval — governance enforcement.
        if (
            enforce
            and final_sensitivity in (Sensitivity.medium, Sensitivity.high)
            and settings.require_approval_for_sensitive
        ):
            return PolicyOutcome(
                Decision.PENDING_APPROVAL,
                candidate,
                f"pending approval: {final_sensitivity.value}-sensitivity content"
                f" ({', '.join(scan_result.pii_labels) or 'flagged'})",
            )

        # 6) Save.
        return PolicyOutcome(Decision.SAVE, candidate, "saved: passed policy checks")

    def evaluate_update(
        self,
        candidate: CandidateMemory,
        *,
        settings: StoredSettings,
    ) -> PolicyOutcome:
        """Evaluate *edited* content for an existing memory.

        Deliberately not ``evaluate()``. Creation runs two steps that are wrong for
        an edit:

          * **dedup / UPDATE_EXISTING** — ``find_similar_active`` would match the
            very memory being edited (or a sibling), turning an edit into a
            reinforcement of itself;
          * **low-utility drop** — an edit to an already-stored memory is not a
            candidate to discard; dropping it would silently keep the old content.

        The safety rules that *do* apply are shared with creation so there is one
        source of truth: secrets and injection BLOCK, PII elevates sensitivity, and
        medium/high sensitivity is gated behind approval.

        Returns ``BLOCK`` (reject the edit, leave the memory untouched),
        ``PENDING_APPROVAL`` (apply the edit but move the memory back to pending), or
        ``SAVE`` (apply the edit).
        """
        enforce = get_app_settings().govern_policy_enforcement
        scan_result = scan(candidate.content)

        if enforce and scan_result.has_secret:
            return PolicyOutcome(
                Decision.BLOCK,
                candidate,
                f"blocked: secret-like content detected ({', '.join(scan_result.secret_labels)})",
            )
        if enforce and scan_result.assessment.recommended_disposition == BLOCK:
            return PolicyOutcome(
                Decision.BLOCK,
                candidate,
                "blocked: disclosed credential or identifier "
                f"({', '.join(scan_result.assessment.categories)})",
            )
        if enforce and scan_result.injection:
            return PolicyOutcome(
                Decision.BLOCK,
                candidate,
                "blocked: prompt-injection / memory-poisoning pattern detected",
            )

        # Sensitivity is recomputed from the *proposed* content, never inherited from
        # the stored row — that inheritance is what let an edit turn a low-sensitivity
        # memory into medical/financial content while keeping its old label.
        final_sensitivity = max(
            candidate.sensitivity,
            Sensitivity(scan_result.sensitivity),
            key=_sensitivity_rank,
        )
        candidate = candidate.model_copy(update={"sensitivity": final_sensitivity})

        if (
            enforce
            and final_sensitivity in (Sensitivity.medium, Sensitivity.high)
            and settings.require_approval_for_sensitive
        ):
            return PolicyOutcome(
                Decision.PENDING_APPROVAL,
                candidate,
                f"pending approval: edited to {final_sensitivity.value}-sensitivity content"
                f" ({', '.join(scan_result.pii_labels) or 'flagged'})",
            )

        return PolicyOutcome(Decision.SAVE, candidate, "edit passed policy checks")


def _sensitivity_rank(s: Sensitivity) -> int:
    return {Sensitivity.low: 0, Sensitivity.medium: 1, Sensitivity.high: 2}[s]
