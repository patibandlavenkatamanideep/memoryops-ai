from __future__ import annotations

import pytest

from app.loops.state_machine import validate_transition
from app.loops.types import LoopState


def test_valid_state_transition_passes():
    validate_transition(None, LoopState.OBSERVED)
    validate_transition(LoopState.OBSERVED, LoopState.CLASSIFIED)
    validate_transition(LoopState.CLASSIFIED, LoopState.POLICY_CHECKED)


def test_invalid_state_transition_fails():
    with pytest.raises(ValueError, match="invalid loop transition"):
        validate_transition(LoopState.OBSERVED, LoopState.COMPLETED)


def test_loop_must_start_observed():
    with pytest.raises(ValueError, match="must start"):
        validate_transition(None, LoopState.EXECUTED)
