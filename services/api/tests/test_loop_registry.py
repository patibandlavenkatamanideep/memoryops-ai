from __future__ import annotations

from app.loops.registry import list_loop_definitions
from app.loops.types import LoopId


def test_loop_registry_contains_required_loops():
    ids = {loop.id for loop in list_loop_definitions()}
    assert {
        LoopId.MEMORY_WRITE,
        LoopId.MEMORY_READ,
        LoopId.MEMORY_GOVERNANCE,
        LoopId.MEMORY_EVALUATION,
        LoopId.RELEASE_GATE,
        LoopId.LEARNING_CONTINUOUS,
    } <= ids


def test_each_loop_has_policy_gates():
    for loop in list_loop_definitions():
        assert loop.policy_gates, loop.id


def test_each_loop_has_failure_modes():
    for loop in list_loop_definitions():
        assert loop.failure_modes, loop.id
