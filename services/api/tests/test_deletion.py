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
