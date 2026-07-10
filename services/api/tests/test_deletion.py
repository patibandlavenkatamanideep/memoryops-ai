"""Deletion guarantee (invariant #2): deleted memory is never retrieved."""

from __future__ import annotations

from app.schemas.memory import ChatRequest, Status


def _chat(gateway, message):
    return gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message=message), trace_id="test"
    )


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
