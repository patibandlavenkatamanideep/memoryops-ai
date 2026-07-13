from __future__ import annotations

from app.loops.types import LoopId, LoopStatus
from app.schemas.memory import ChatRequest


def test_memory_write_loop_emits_events(gateway, repo):
    resp = gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message="Remember that I prefer loops."),
        trace_id="trace-write",
    )
    runs = repo.list_loop_runs(loop_id=LoopId.MEMORY_WRITE.value, trace_id="trace-write")
    assert runs
    assert runs[0].status == LoopStatus.COMPLETED
    assert resp.loop_evidence[LoopId.MEMORY_WRITE.value] == "completed"
    states = [e.state_to.value for e in repo.list_loop_events(loop_run_id=runs[0].id)]
    assert "observed" in states
    assert "policy_checked" in states
    assert "audited" in states
    assert "completed" in states


def test_multi_memory_write_emits_single_policy_checked(gateway, repo):
    """A message that extracts *several* memories must not 500.

    Regression: the write loop emitted POLICY_CHECKED once per candidate, so a
    multi-memory extraction (P1.3) produced an invalid
    policy_checked -> policy_checked transition and a 500. The loop models one
    policy gate per run, so exactly one POLICY_CHECKED event must be emitted no
    matter how many memories the turn yields.
    """
    resp = gateway.handle_chat(
        ChatRequest(
            tenant_id="t1",
            user_id="u1",
            message="Remember that I prefer metric units. I work in the Pacific timezone.",
        ),
        trace_id="trace-multi",
    )
    # Genuinely a multi-memory turn.
    assert len(resp.candidate_memories) >= 2

    runs = repo.list_loop_runs(loop_id=LoopId.MEMORY_WRITE.value, trace_id="trace-multi")
    assert runs and runs[0].status == LoopStatus.COMPLETED
    assert resp.loop_evidence[LoopId.MEMORY_WRITE.value] == "completed"

    states = [e.state_to.value for e in repo.list_loop_events(loop_run_id=runs[0].id)]
    assert states.count("policy_checked") == 1, states
    assert states.count("executed") == 1, states
