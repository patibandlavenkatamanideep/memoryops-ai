"""Tombstone lineage + deleted-memory leakage (v1.4, ADR-018).

Proves the deletion guarantee (#2) propagates to *derived* artifacts: a memory
derived from a deleted ancestor cannot enter context, and a deleted memory does
not influence output directly, indirectly, or after a re-query.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db import lineage
from app.db.entities import StoredMemory
from app.db.memory_repo import InMemoryRepository
from app.schemas.memory import (
    ChatRequest,
    MemoryType,
    Sensitivity,
    Source,
    Status,
)
from app.services.admission_gate import AdmissionDecision, AdmissionGate
from app.services.ranker import RankedMemory
from app.services.retriever import ScoredCandidate


def _mem(**kw) -> StoredMemory:
    defaults = dict(
        tenant_id="t1", user_id="u1", memory_type=MemoryType.semantic,
        content="derived summary", importance=6, confidence=0.9,
        sensitivity=Sensitivity.low, status=Status.active, source=Source(kind="reflection"),
    )
    defaults.update(kw)
    return StoredMemory(**defaults)


def _ranked(memory: StoredMemory, score: float = 0.8) -> RankedMemory:
    cand = ScoredCandidate(memory=memory, semantic=score, keyword=0.5)
    return RankedMemory(candidate=cand, score=score, score_breakdown={"vector_similarity": score})


# ── lineage helpers ────────────────────────────────────────────────────────────
def test_set_lineage_records_parents_and_root():
    m = _mem()
    lineage.set_lineage(m, parent_ids=["p1"])
    assert lineage.parent_ids(m) == ["p1"]
    assert lineage.lineage_root_id(m) == "p1"  # single parent → root defaults to it
    assert lineage.is_derived(m)


def test_derived_metadata_builds_lineage_block():
    meta = lineage.derived_metadata(parent_ids=["a", "b"], lineage_root_id="a",
                                    source_event_id="evt1", base={"pinned": True})
    m = _mem(metadata=meta)
    assert lineage.parent_ids(m) == ["a", "b"]
    assert lineage.lineage_root_id(m) == "a"
    assert lineage.source_event_id(m) == "evt1"
    assert m.metadata["pinned"] is True  # base preserved


def test_tombstone_marker_and_soft_delete_both_count():
    m = _mem()
    assert not lineage.is_tombstoned(m)
    lineage.set_tombstone(m, on=True, reason="deleted", now=datetime.now(UTC))
    assert lineage.is_tombstoned(m)
    # A soft-deleted row is a tombstone even without the explicit marker.
    d = _mem(status=Status.deleted)
    assert lineage.is_tombstoned(d)


# ── ancestry resolution (fail-closed) ──────────────────────────────────────────
def test_ancestry_clean_when_parent_active():
    store = {}
    parent = _mem(id="p", content="parent", status=Status.active)
    child = _mem(id="c")
    lineage.set_lineage(child, parent_ids=["p"])
    store["p"] = parent
    assert lineage.ancestry_tombstone(child, store.get) is None


def test_ancestry_blocks_on_deleted_parent():
    parent = _mem(id="p", status=Status.deleted)
    child = _mem(id="c")
    lineage.set_lineage(child, parent_ids=["p"])
    assert lineage.ancestry_tombstone(child, {"p": parent}.get) == "p"


def test_ancestry_blocks_on_missing_parent_fail_closed():
    child = _mem(id="c")
    lineage.set_lineage(child, parent_ids=["gone"])
    assert lineage.ancestry_tombstone(child, {}.get) == "gone"


def test_ancestry_is_transitive():
    grand = _mem(id="g", status=Status.deleted)
    parent = _mem(id="p", status=Status.active)
    lineage.set_lineage(parent, parent_ids=["g"])
    child = _mem(id="c")
    lineage.set_lineage(child, parent_ids=["p"])
    store = {"g": grand, "p": parent}
    assert lineage.ancestry_tombstone(child, store.get) == "g"


def test_ancestry_cycle_is_safe():
    a = _mem(id="a")
    b = _mem(id="b")
    lineage.set_lineage(a, parent_ids=["b"])
    lineage.set_lineage(b, parent_ids=["a"])  # cycle, both active
    store = {"a": a, "b": b}
    # No tombstone present → returns None without looping forever.
    assert lineage.ancestry_tombstone(a, store.get) is None


# ── admission gate integration ─────────────────────────────────────────────────
def test_gate_blocks_derived_from_tombstoned_ancestor():
    parent = _mem(id="p", status=Status.deleted)
    child = _mem(id="c")
    lineage.set_lineage(child, parent_ids=["p"])
    result = AdmissionGate().evaluate(
        [_ranked(child)], tenant_id="t1", user_id="u1", ancestor_lookup={"p": parent}.get
    )
    assert result.records[0].decision is AdmissionDecision.BLOCK_TOMBSTONED_ANCESTOR


def test_gate_allows_derived_when_no_lookup_provided():
    # Backward-compatible: without a resolver the ancestry check is skipped.
    child = _mem(id="c")
    lineage.set_lineage(child, parent_ids=["p"])
    result = AdmissionGate().evaluate([_ranked(child)], tenant_id="t1", user_id="u1")
    assert result.records[0].decision is AdmissionDecision.ALLOW


# ── end-to-end through the gateway ─────────────────────────────────────────────
def _chat(gw, message):
    return gw.handle_chat(ChatRequest(tenant_id="t1", user_id="u1", message=message), trace_id="x")


def test_gateway_blocks_derived_after_parent_deleted():
    from app.services.gateway import Gateway

    repo = InMemoryRepository()
    gw = Gateway(repo)
    parent = _mem(id="p", memory_type=MemoryType.preference,
                  content="user prefers Vendor X for cloud", source=Source(kind="chat"))
    repo.create_memory(parent)
    derived = _mem(id="d", content="summary: the user consistently chooses Vendor X for cloud")
    lineage.set_lineage(derived, parent_ids=["p"])
    repo.create_memory(derived)

    before = _chat(gw, "Which cloud vendor do I prefer?")
    assert "d" in {u.memory_id for u in before.used_memories}

    repo.soft_delete("t1", "u1", "p")
    lineage.set_tombstone(parent, on=True, reason="deleted")
    repo.update_memory(parent)

    after = _chat(gw, "Which cloud vendor do I prefer?")
    assert "d" not in {u.memory_id for u in after.used_memories}
    blocked = {e.memory_id: e.admission_decision for e in after.trace.memories_blocked}
    assert blocked.get("d") == "BLOCK_TOMBSTONED_ANCESTOR"


def test_delete_route_stamps_tombstone(api_client):
    client, repo = api_client
    client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1",
                                   "message": "Remember I prefer Vendor X for cloud."})
    mem = repo.list_memories("t1", "u1")[0]
    resp = client.request("DELETE", f"/api/memories/{mem.id}",
                          json={"tenant_id": "t1", "user_id": "u1"})
    assert resp.status_code == 200
    deleted = repo.get_memory("t1", "u1", mem.id)
    assert deleted.status is Status.deleted
    assert lineage.is_tombstoned(deleted)


def test_deleted_memory_does_not_leak_across_probes(gateway, repo):
    _chat(gateway, "Remember that I prefer Vendor X for all cloud deployments.")
    row = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", row.id)
    for probe in ("Which vendor do I prefer?",
                  "Based on my past choices, what should I pick?",
                  "Can you infer which provider I liked before?"):
        resp = _chat(gateway, probe)
        used = " ".join(u.content.lower() for u in resp.used_memories)
        assert "vendor x" not in used
        assert "vendor x" not in resp.assistant_message.lower()
        assert row.id not in {u.memory_id for u in resp.used_memories}
