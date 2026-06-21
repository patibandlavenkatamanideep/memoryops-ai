"""Loop state transition validator."""

from __future__ import annotations

from .types import LoopState

ALLOWED_TRANSITIONS: dict[LoopState, set[LoopState]] = {
    LoopState.OBSERVED: {
        LoopState.CLASSIFIED,
        LoopState.POLICY_CHECKED,
        LoopState.EXECUTED,
        LoopState.FAILED,
    },
    LoopState.CLASSIFIED: {LoopState.POLICY_CHECKED, LoopState.FAILED},
    LoopState.POLICY_CHECKED: {
        LoopState.EXECUTED,
        LoopState.SAFE_DEGRADED,
        LoopState.FAILED,
    },
    LoopState.EXECUTED: {
        LoopState.VERIFIED,
        LoopState.AUDITED,
        LoopState.SAFE_DEGRADED,
        LoopState.FAILED,
    },
    LoopState.VERIFIED: {LoopState.AUDITED, LoopState.FAILED},
    LoopState.AUDITED: {
        LoopState.FEEDBACK_CAPTURED,
        LoopState.LEARNED,
        LoopState.COMPLETED,
    },
    LoopState.FEEDBACK_CAPTURED: {LoopState.LEARNED, LoopState.COMPLETED},
    LoopState.LEARNED: {LoopState.COMPLETED},
    LoopState.SAFE_DEGRADED: {LoopState.AUDITED, LoopState.COMPLETED},
    LoopState.FAILED: {LoopState.AUDITED},
}


def validate_transition(current: LoopState | None, next_state: LoopState) -> None:
    if current is None:
        if next_state != LoopState.OBSERVED:
            raise ValueError(f"loop must start at observed, got {next_state.value}")
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if next_state not in allowed:
        allowed_values = ", ".join(sorted(s.value for s in allowed)) or "(terminal)"
        raise ValueError(
            f"invalid loop transition {current.value} -> {next_state.value}; "
            f"allowed next states: {allowed_values}"
        )
