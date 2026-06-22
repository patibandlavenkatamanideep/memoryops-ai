"""End-to-end tests — the SDK against the real MemoryOps FastAPI app, in process.

These prove the SDK matches the *live* contract (paths, scopes, governance
behavior), not a mock. Skipped automatically if the API package isn't importable
(see conftest.live_client).
"""

from __future__ import annotations

import pytest


def test_chat_then_list_roundtrip(live_client) -> None:
    result = live_client.chat("Remember that I prefer dark mode dashboards.")
    assert result.assistant_message
    assert result.trace_id

    memories = live_client.list_memories()
    assert any("dark mode" in m.content for m in memories)


def test_legal_hold_blocks_delete_then_release_allows(live_client) -> None:
    from memoryops import LegalHoldError

    live_client.chat("Remember my account id is 12345.")
    memory = live_client.list_memories()[0]

    live_client.set_legal_hold(memory.id, on=True, reason="audit")
    with pytest.raises(LegalHoldError):
        live_client.delete_memory(memory.id)

    live_client.set_legal_hold(memory.id, on=False)
    out = live_client.delete_memory(memory.id)
    assert out["status"] == "deleted"


def test_retention_decisions_and_policies(live_client) -> None:
    live_client.chat("Remember I like espresso.")
    policies = live_client.retention_policies()
    assert {"default", "strict", "extended"} <= {p["name"] for p in policies}

    decisions = live_client.retention_decisions()
    assert all(d.memory_id for d in decisions)


def test_consent_withdrawal_is_recorded(live_client) -> None:
    live_client.chat("Remember I live in Berlin.")
    memory = live_client.list_memories()[0]
    live_client.set_consent(memory.id, status="withdrawn")
    gov = live_client.memory_governance(memory.id)
    assert gov["governance"]["consent_status"] == "withdrawn"


def test_temporary_chat_writes_nothing(live_client) -> None:
    before = len(live_client.list_memories())
    live_client.chat("Remember a temporary secret.", temporary_chat=True)
    assert len(live_client.list_memories()) == before


def test_audit_trail_is_readable(live_client) -> None:
    live_client.chat("Remember I prefer tabs.")
    events = live_client.audit(limit=10)
    assert any(e.action for e in events)
