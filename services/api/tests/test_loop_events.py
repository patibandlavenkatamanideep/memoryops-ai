from __future__ import annotations

import asyncio

from app.loops.events import emit_loop_event, start_loop_run
from app.loops.types import LoopId, LoopState


def test_loop_events_do_not_store_raw_secret(repo):
    async def _run():
        run = await start_loop_run(
            repo,
            LoopId.MEMORY_WRITE,
            "trace-secret",
            tenant_id="t1",
            user_id="u1",
            metadata={"raw": "api_key=sk-test-123456789abcdefghij"},
        )
        await emit_loop_event(
            repo,
            run,
            LoopState.OBSERVED,
            event_type="secret_observed",
            reason="secret-like content seen",
            evidence={"candidate": "password=hunter2"},
        )

    asyncio.run(_run())
    event_blob = repo.list_loop_events(trace_id="trace-secret")[0].model_dump_json()
    run_blob = repo.list_loop_runs(trace_id="trace-secret")[0].model_dump_json()
    assert "sk-test" not in event_blob
    assert "hunter2" not in event_blob
    assert "sk-test" not in run_blob


def test_async_loop_helpers_persist_events(repo):
    async def _run():
        run = await start_loop_run(repo, LoopId.MEMORY_EVALUATION, "trace-eval")
        event = await emit_loop_event(
            repo,
            run,
            LoopState.OBSERVED,
            event_type="eval_observed",
            reason="eval run started",
        )
        return run, event

    run, event = asyncio.run(_run())
    assert repo.list_loop_runs(trace_id="trace-eval")[0].id == run.id
    assert repo.list_loop_events(loop_run_id=run.id)[0].id == event.id
