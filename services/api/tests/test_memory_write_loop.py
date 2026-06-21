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
