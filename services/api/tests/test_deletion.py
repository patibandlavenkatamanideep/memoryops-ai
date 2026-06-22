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
