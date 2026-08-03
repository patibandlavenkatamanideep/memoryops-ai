from __future__ import annotations

import asyncio

from app.loops.events import emit_loop_event, start_loop_run
from app.loops.types import LoopId, LoopState

from ._secret_fixtures import FAKE_PROVIDER_KEY, FAKE_SECRET_IN_METADATA


def test_loop_events_do_not_store_raw_secret(repo):
    async def _run():
        run = await start_loop_run(
            repo,
            LoopId.MEMORY_WRITE,
            "trace-secret",
            tenant_id="t1",
            user_id="u1",
            metadata={"raw": FAKE_SECRET_IN_METADATA},
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


def test_governed_content_update_emits_a_full_governance_loop(api_client):
    """A content edit is a governance loop run, not a bare field assignment.

    The edit path now runs through the policy broker, so its loop trace must show
    the same Observe → PolicyChecked → Executed → Verified → Audited → Completed
    evidence every other governed mutation produces — with the audit event carrying
    the decision rather than a generic `memory_updated`.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    m = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="prefers dark mode",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="prefers dark mode"),
        )
    )

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "prefers light mode"},
    )
    assert r.status_code == 200

    runs = repo.list_loop_runs(tenant_id="t1", user_id="u1", limit=50)
    edit_runs = [x for x in runs if (x.metadata or {}).get("memory_id") == m.id]
    assert edit_runs, "the content edit produced no governance loop run"

    events = repo.list_loop_events(loop_run_id=edit_runs[0].id)
    states = {e.state_to.value for e in events}
    for required in ("observed", "policy_checked", "executed", "verified", "audited"):
        assert required in states, f"missing loop state: {required}"

    # The audit event linked from the loop reflects the governed decision.
    audited = [e for e in events if e.state_to.value == "audited"]
    assert audited and audited[0].audit_event_id
    trail = client.get(f"/api/memories/{m.id}/audit?tenant_id=t1&user_id=u1").json()
    assert "memory_content_updated" in {e["action"] for e in trail}


def test_a_blocked_content_edit_does_not_emit_an_executed_state(api_client):
    """A refused edit must not leave evidence suggesting a write happened."""
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    m = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="prefers dark mode",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="prefers dark mode"),
        )
    )

    blocked = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": FAKE_PROVIDER_KEY},
    )
    assert blocked.status_code == 422

    runs = repo.list_loop_runs(tenant_id="t1", user_id="u1", limit=50)
    edit_runs = [x for x in runs if (x.metadata or {}).get("memory_id") == m.id]
    for run in edit_runs:
        states = {e.state_to.value for e in repo.list_loop_events(loop_run_id=run.id)}
        assert "executed" not in states, "a blocked edit must not record an execution"
    assert repo.get_memory("t1", "u1", m.id).content == "prefers dark mode"


def test_a_blocked_credential_disclosure_records_no_write(api_client):
    """A semantic credential disclosure is refused before storage, and the loop
    evidence must not suggest a write happened.

    "my password is hunter2" has no key-like *shape*, so the structural scanner
    never saw it; it was stored active at `low` sensitivity, which left every
    sensitivity-keyed control inert for it.
    """
    client, repo = api_client
    r = client.post(
        "/api/chat",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "message": "Remember: my password is hunter2.",
        },
    )
    assert r.status_code == 200

    # Nothing stored, and the chat response records the refusal as a decision.
    assert [m for m in repo.list_memories("t1", "u1")] == []
    decisions = {c["decision"] for c in r.json()["candidate_memories"]}
    assert "BLOCK" in decisions


def test_a_memory_control_instruction_records_no_stored_candidate(api_client):
    """No memory, and no BLOCK either — there was never a candidate to refuse."""
    client, repo = api_client
    r = client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "do not remember my password"},
    )
    assert r.status_code == 200
    assert repo.list_memories("t1", "u1") == []
    assert r.json()["candidate_memories"] == []
