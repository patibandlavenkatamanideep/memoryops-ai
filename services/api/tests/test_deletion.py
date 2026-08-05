"""Deletion guarantee (invariant #2): deleted memory is never retrieved."""

from __future__ import annotations

import pytest

from app.schemas.memory import ChatRequest, Status


def _chat(gateway, message):
    return gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message=message), trace_id="test"
    )


def test_delete_route_is_atomic_when_audit_fails(api_client, monkeypatch) -> None:
    """v2.3 (P0): soft-deletion + tombstone + audit are one atomic unit of work.

    If the audit append fails mid-delete, the deletion rolls back — the memory is
    neither soft-deleted nor tombstoned, so we never persist a half-deleted memory
    (a mutation without its evidence)."""
    from app.db import lineage

    client, repo = api_client
    client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "Remember I prefer Vendor X."},
    )
    mem = repo.list_memories("t1", "u1")[0]

    def _boom(_event):
        raise RuntimeError("audit backend down")

    monkeypatch.setattr(repo, "add_audit", _boom)

    with pytest.raises(RuntimeError):
        client.request(
            "DELETE", f"/api/memories/{mem.id}", json={"tenant_id": "t1", "user_id": "u1"}
        )

    survived = repo.get_memory("t1", "u1", mem.id)
    assert survived.status is Status.active  # rolled back — still active
    assert not lineage.is_tombstoned(survived)
    assert mem.id in {m.id for m in repo.retrieve_active("t1", "u1")}


def test_deleted_memory_excluded_from_retrieval(gateway, repo):
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]

    deleted = repo.soft_delete("t1", "u1", mem.id)
    assert deleted.status == Status.deleted
    assert deleted.deleted_at is not None

    # Not in active retrieval, not in default listing.
    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}
    # Still visible with include_deleted (for audit/forensics).
    assert mem.id in {m.id for m in repo.list_memories("t1", "u1", include_deleted=True)}


def test_delete_is_tenant_scoped(gateway, repo):
    _chat(gateway, "Remember that I prefer dark mode.")
    mem = repo.list_memories("t1", "u1")[0]
    # Wrong scope cannot delete.
    assert repo.soft_delete("t1", "other", mem.id) is None
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active


def test_deleted_memory_excluded_from_vector_search(gateway, repo):
    # The v0.3 vector candidate path must honor the deletion guarantee too.
    from app.embeddings import embed

    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)
    pairs = repo.search_candidates("t1", "u1", embed("dark mode dashboards"))
    assert all(m.id != mem.id for m, _ in pairs)


def test_control_plane_detail_marks_deleted_never_active(gateway, repo):
    # v0.5: the control-plane detail/provenance path may return a soft-deleted
    # row for forensics, but its status must remain `deleted` (never active) and
    # it must stay out of the active inventory listing.
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)

    fetched = repo.get_memory("t1", "u1", mem.id)
    assert fetched is not None
    assert fetched.status == Status.deleted  # carries truth; UI renders deleted
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}


def test_compacted_deleted_memory_stays_unreachable(gateway, repo):
    # v0.7: after the repository compacts a soft-deleted memory (clears content +
    # vector material), the deletion guarantee must still hold and the tombstone
    # must remain (status stays deleted, never resurrected).
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)

    compacted = repo.compact_deleted_memory("t1", "u1", mem.id, reason="test")
    assert compacted is not None
    assert compacted.status == Status.deleted  # tombstone, never reactivated
    assert compacted.content == "" and compacted.embedding == []

    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}
    assert all(m.id != mem.id for m, _ in repo.search_candidates("t1", "u1", []))


def test_compaction_rejects_active_memory(gateway, repo):
    # Active memory is never eligible for compaction (only deleted rows are).
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    assert repo.compact_deleted_memory("t1", "u1", mem.id, reason="x") is None
    assert repo.get_memory("t1", "u1", mem.id).content != ""


def test_worker_runtime_preserves_deletion_guarantee(gateway, repo):
    # v0.8: running the scheduled worker runtime over a scope that has a deleted
    # memory must keep the deletion guarantee (the run record is content-free and
    # the deleted row stays unreachable / never resurrected).
    from app.workers.orchestrator import Scope, WorkerOrchestrator
    from app.workers.retry import RetryPolicy

    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)

    orch = WorkerOrchestrator(
        repo, owner="t", retry_policy=RetryPolicy(max_attempts=1), sleep=lambda _s: None
    )
    rec = orch.run_scope(Scope("t1", "u1"))

    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}
    assert repo.get_memory("t1", "u1", mem.id).status == Status.deleted
    # Run record carries no memory content (ids/counts/status only).
    assert "dark mode" not in str(rec.details)


def test_retention_deletion_preserves_deletion_guarantee(gateway, repo):
    # v0.10: a memory the retention worker soft-deletes (expired window) must obey
    # the deletion guarantee exactly like any other delete — gone from retrieval
    # and default listing, never resurrected.
    from app.db import governance as gov
    from app.workers.retention import RetentionWorker

    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    gov.set_consent(mem, status=gov.ConsentStatus.withdrawn)
    repo.update_memory(mem)

    RetentionWorker(repo, enabled=True).run(_ctx_for(mem))

    assert repo.get_memory("t1", "u1", mem.id).status == Status.deleted
    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}


def test_legal_hold_blocks_soft_delete_path(gateway, repo):
    # v0.10: legal hold is fail-closed — the retention worker never deletes a held
    # memory, so the active row survives even when otherwise eligible.
    from app.db import governance as gov
    from app.workers.retention import RetentionWorker

    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    gov.set_consent(mem, status=gov.ConsentStatus.withdrawn)
    gov.set_legal_hold(mem, on=True, reason="hold")
    repo.update_memory(mem)

    RetentionWorker(repo, enabled=True).run(_ctx_for(mem))
    assert repo.get_memory("t1", "u1", mem.id).status == Status.active


def _ctx_for(mem):
    from app.workers.lifecycle import WorkerContext

    return WorkerContext(tenant_id=mem.tenant_id, user_id=mem.user_id)


def test_deletion_guarantee_propagates_to_derived_artifacts(gateway, repo):
    # v1.4: the deletion guarantee extends to *derived* artifacts via tombstone
    # lineage. A memory derived from a deleted ancestor must not enter context
    # (BLOCK_TOMBSTONED_ANCESTOR), even though it is itself an active row.
    from app.db import lineage
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source

    _chat(gateway, "Remember that I prefer Vendor X for cloud deployments.")
    parent = repo.list_memories("t1", "u1")[0]
    derived = StoredMemory(
        tenant_id="t1", user_id="u1", memory_type=MemoryType.semantic,
        content="summary: the user consistently chooses Vendor X for cloud",
        importance=6, confidence=0.9, sensitivity=Sensitivity.low,
        status=Status.active, source=Source(kind="reflection"),
    )
    lineage.set_lineage(derived, parent_ids=[parent.id])
    repo.create_memory(derived)

    repo.soft_delete("t1", "u1", parent.id)
    lineage.set_tombstone(parent, on=True, reason="deleted")
    repo.update_memory(parent)

    resp = _chat(gateway, "Which cloud vendor do I prefer?")
    assert derived.id not in {u.memory_id for u in resp.used_memories}
    assert "vendor x" not in resp.assistant_message.lower()


def test_deletion_is_covered_by_tamper_evident_audit_chain(gateway, repo):
    # v2.0 (ADR-024): a deletion's audit event joins the tamper-evident hash chain, so
    # the deletion is provable and the chain stays intact after it.
    from app.evidence.reports import deletion_proof, verify_audit

    _chat(gateway, "Remember that I prefer Vendor X.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)
    proof = deletion_proof(repo, "t1", "u1", mem.id)
    assert proof["found"] and proof["checks"]["status_is_deleted"]
    assert proof["checks"]["excluded_from_active_retrieval"]
    assert verify_audit(repo, "t1")["ok"]  # chain intact through the deletion


def test_deletion_removes_vector_from_index_seam(gateway, repo):
    # v1.7: with similarity delegated to the pluggable VectorIndex, deletion must
    # remove the vector so the row can never come back as a scored candidate — the
    # deletion guarantee (#2) must not be weakened by the swappable backend.
    from app.embeddings import embed

    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    q = embed("dark mode dashboards")
    assert repo.search_candidates("t1", "u1", q)  # present before deletion

    repo.soft_delete("t1", "u1", mem.id)
    # Gone from the vector candidate path and from active retrieval.
    assert repo.search_candidates("t1", "u1", q) == []
    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}


def test_loop_traces_do_not_resurrect_deleted_memory(gateway, repo):
    # v0.3.1: loop runs/events are operational evidence stored alongside the
    # write path. They must never re-expose a soft-deleted memory in retrieval.
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    mem = repo.list_memories("t1", "u1")[0]
    repo.soft_delete("t1", "u1", mem.id)

    # The write loop trace still exists (operational forensics) ...
    assert repo.list_loop_runs(tenant_id="t1", user_id="u1") != []
    # ... but the deletion guarantee continues to hold.
    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}
    assert mem.id not in {m.id for m in repo.list_memories("t1", "u1")}


def test_patch_cannot_produce_a_deleted_row_outside_the_deletion_workflow(api_client):
    """The deletion guarantee has exactly one entry point.

    `PATCH {"status": "deleted"}` used to write `status=deleted` directly, producing
    a row that satisfied the *retrieval* half of invariant #2 (hidden) while
    violating everything the deletion workflow exists to provide: `deleted_at` was
    null, so retention and compaction never reclaimed it; no tombstone was stamped,
    so lineage could not propagate it to derived memories; and the audit trail
    recorded a generic `memory_updated`. Full coverage in
    tests/test_status_transition_bypass.py.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    mem = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="dark mode",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="dark mode"),
        )
    )

    r = client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "deleted"},
    )
    assert r.status_code == 422

    after = repo.get_memory("t1", "u1", mem.id)
    assert after.status is Status.active
    assert after.deleted_at is None
    # Still retrievable: the row was never deleted, so it must not have been hidden.
    assert mem.id in {m.id for m in repo.retrieve_active("t1", "u1")}


def test_the_deletion_workflow_still_satisfies_the_invariant(api_client):
    """Closing the PATCH bypass must not weaken real deletion."""
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    mem = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="dark mode",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="dark mode"),
        )
    )

    r = client.request(
        "DELETE", f"/api/memories/{mem.id}", json={"tenant_id": "t1", "user_id": "u1"}
    )
    assert r.status_code == 200

    after = repo.get_memory("t1", "u1", mem.id)
    assert after.status is Status.deleted
    assert after.deleted_at is not None, "the workflow stamps deleted_at; PATCH never did"
    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}


def test_a_content_edit_never_resurrects_or_hides_a_memory(api_client):
    """The governed update path must not touch deletion state.

    Editing goes through `update_service`, which changes content, sensitivity,
    embedding, and revision — never `status=deleted` or `deleted_at`. A deleted
    memory is not editable at all (404), so an edit can neither resurrect one nor
    quietly delete a live one.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    live = repo.create_memory(
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
        f"/api/memories/{live.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "prefers light mode"},
    )
    assert r.status_code == 200
    after = repo.get_memory("t1", "u1", live.id)
    assert after.status is Status.active
    assert after.deleted_at is None
    assert live.id in {m.id for m in repo.retrieve_active("t1", "u1")}

    gone = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="already deleted",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.deleted,
            source=Source(kind="chat", excerpt="already deleted"),
        )
    )
    edit = client.patch(
        f"/api/memories/{gone.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "resurrected"},
    )
    assert edit.status_code == 404
    assert repo.get_memory("t1", "u1", gone.id).content == "already deleted"


def test_the_authorization_lookup_is_not_a_retrieval_path(api_client):
    """`get_memory_in_tenant` (v2.4) is new reach across a tenant, so the deletion
    guarantee has to be re-proved against it.

    Ownership authorization has to inspect a record *before* it knows the owner, so
    this lookup spans users and returns soft-deleted rows — otherwise "not yours"
    and "does not exist" would be indistinguishable. That makes it the one place a
    deleted memory is legitimately readable inside the process, and therefore the
    one place a careless caller could turn it back into a retrieval path.

    The invariant is that nothing downstream of it re-enters retrieval or context.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    secret = "renews the enterprise contract in March"
    mem = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.semantic,
            content=secret,
            importance=8,
            confidence=0.95,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt=secret),
        )
    )
    assert client.request(
        "DELETE", f"/api/memories/{mem.id}", json={"tenant_id": "t1", "user_id": "u1"}
    ).status_code == 200

    # The lookup still sees it — deliberately, and it is the only thing that does.
    assert repo.get_memory_in_tenant("t1", mem.id) is not None

    # None of the retrieval surfaces do.
    assert repo.retrieve_active("t1", "u1") == []
    assert repo.search_candidates("t1", "u1", [0.1] * 8, limit=10) == []
    assert [m.id for m in repo.list_memories("t1", "u1")] == []

    # And a chat response neither uses it nor repeats it.
    chat = client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "when does the contract renew?"},
    )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert secret not in chat.text
    assert mem.id not in {u["memory_id"] for u in body.get("used_memories", [])}


def test_the_deletion_workflow_survives_authorization_being_moved_ahead_of_it(api_client):
    """v2.4 reordered DELETE: authorize, *then* open the loop, check legal hold, and
    run the deletion transaction.

    The risk in moving a check earlier is that something it used to run after now
    runs before, or not at all. This pins the whole sequence still happening with
    auth disabled — the development default, and the configuration the rest of this
    suite runs under.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    mem = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="dark mode",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="dark mode"),
        )
    )
    runs_before = len(repo.list_loop_runs(tenant_id="t1", user_id="u1", limit=1000))

    r = client.request(
        "DELETE", f"/api/memories/{mem.id}", json={"tenant_id": "t1", "user_id": "u1"}
    )
    assert r.status_code == 200

    after = repo.get_memory("t1", "u1", mem.id)
    assert after.status is Status.deleted
    assert after.deleted_at is not None, "the workflow still stamps deleted_at"
    assert after.metadata["lineage"]["tombstoned"] is True, (
        "tombstone lineage must still be stamped after the reorder"
    )
    assert mem.id not in {m.id for m in repo.retrieve_active("t1", "u1")}

    # The governance loop still runs — authorization moved ahead of it, not over it.
    assert len(repo.list_loop_runs(tenant_id="t1", user_id="u1", limit=1000)) > runs_before
    actions = {a.action for a in repo.list_audit("t1", "u1", memory_id=mem.id, limit=50)}
    assert any("delet" in a for a in actions), actions


def test_a_missing_memory_is_still_not_deletable(api_client):
    client, _repo = api_client
    r = client.request(
        "DELETE", "/api/memories/does-not-exist", json={"tenant_id": "t1", "user_id": "u1"}
    )
    assert r.status_code == 404


def test_loop_evidence_outlives_a_deleted_memory_without_carrying_its_content(api_client):
    """Governance evidence is *meant* to survive deletion — that is what proves the
    deletion happened. So the deletion guarantee depends on those records never
    having held the content in the first place.

    Tightening the loop queries in v2.4 made them tenant-scoped; this pins the other
    half, that what they return is content-free even for a memory that is now gone.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    secret = "the acquisition closes on the fourteenth"
    mem = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.semantic,
            content=secret,
            importance=8,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt=secret),
        )
    )
    assert client.patch(
        f"/api/memories/{mem.id}", json={"tenant_id": "t1", "user_id": "u1", "importance": 9}
    ).status_code == 200
    assert client.request(
        "DELETE", f"/api/memories/{mem.id}", json={"tenant_id": "t1", "user_id": "u1"}
    ).status_code == 200

    runs = repo.list_loop_runs(tenant_id="t1", user_id="u1", limit=1000)
    events = repo.list_loop_events(tenant_id="t1", user_id="u1", limit=1000)
    assert runs and events, "the evidence that the deletion happened must survive"

    blob = "".join(r.model_dump_json() for r in runs) + "".join(
        e.model_dump_json() for e in events
    )
    assert secret not in blob
    assert "acquisition" not in blob

    # The same holds for what the API serves.
    served = client.get("/api/loops/runs?tenant_id=t1&user_id=u1").text
    served += client.get("/api/loops/events?tenant_id=t1&user_id=u1").text
    assert secret not in served
