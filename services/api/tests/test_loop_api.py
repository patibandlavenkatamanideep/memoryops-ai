from __future__ import annotations

from app.loops.registry import list_loop_definitions
from app.loops.types import LoopId, LoopTrace
from app.schemas.memory import ChatRequest


def test_loop_api_returns_definitions():
    ids = {item.id.value for item in list_loop_definitions()}
    assert LoopId.MEMORY_WRITE.value in ids
    assert LoopId.RELEASE_GATE.value in ids


def test_trace_endpoint_returns_timeline(gateway, repo):
    gateway.handle_chat(
        ChatRequest(
            tenant_id="t1",
            user_id="u1",
            message="Remember that I prefer loop timelines.",
        ),
        trace_id="trace-api",
    )
    body = LoopTrace(
        trace_id="trace-api",
        runs=repo.list_loop_runs(trace_id="trace-api"),
        events=repo.list_loop_events(trace_id="trace-api"),
    )
    assert body.trace_id == "trace-api"
    assert body.runs
    assert body.events
