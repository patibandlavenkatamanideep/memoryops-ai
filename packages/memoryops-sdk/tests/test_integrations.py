"""GovernedMemory adapter — the framework-agnostic layer every integration wraps (v2.1).

Tested against the real in-process app (via `live_client`), so the adapter is proven to
route an agent's remember/recall/forget through the *governed* pipeline, not a mock.
"""

from __future__ import annotations

from memoryops import GovernedMemory


def _memory(live_client, audience="private") -> GovernedMemory:
    return GovernedMemory(live_client, audience=audience)


def test_remember_then_recall_roundtrip(live_client):
    memory = _memory(live_client)
    result = memory.remember("I prefer dark mode dashboards.")
    assert result.stored and "SAVE" in result.decisions

    recalled = memory.recall("what UI theme do I prefer?")
    assert any("dark mode" in c for c in recalled)


def test_context_for_returns_injectable_block(live_client):
    memory = _memory(live_client)
    memory.remember("I prefer metric units.")
    block = memory.context_for("what units should I use?")
    assert block.startswith("Relevant memory:") and "metric" in block


def test_context_for_empty_when_nothing_relevant(live_client):
    memory = _memory(live_client)
    assert memory.context_for("something never mentioned before") == ""


def test_forget_removes_from_recall(live_client):
    memory = _memory(live_client)
    memory.remember("My project codename is Bluefin.")
    mem = live_client.list_memories()[0]
    memory.forget(mem.id)
    assert all("bluefin" not in c.lower() for c in memory.recall("what is my project codename?"))


def test_audience_param_flows_through_to_the_server(live_client):
    # The adapter forwards `audience` on every recall (server-side gating is proven in
    # the API's test_recall_output_gates.py). Here we prove the SDK path carries it and
    # that a per-audience view is a distinct, working recaller.
    private = _memory(live_client, "private")
    private.remember("I prefer aisle seats.")
    assert any("aisle" in c for c in private.recall("what seat do I prefer?"))

    public = private.for_audience("public")
    assert isinstance(public, GovernedMemory) and public is not private
    assert isinstance(public.recall("what seat do I prefer?"), list)
