"""Tenant isolation (invariant #1): no cross-tenant / cross-user retrieval."""

from __future__ import annotations

from app.schemas.memory import ChatRequest


def _chat(gateway, tenant, user, message):
    return gateway.handle_chat(
        ChatRequest(tenant_id=tenant, user_id=user, message=message), trace_id="test"
    )


def test_other_tenant_memory_not_retrieved(gateway, repo):
    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    # A different tenant must see nothing.
    assert repo.retrieve_active("tenant_demo", "user_demo") == []
    assert repo.list_memories("tenant_demo", "user_demo") == []


def test_other_user_same_tenant_not_retrieved(gateway, repo):
    _chat(gateway, "t1", "alice", "Remember Alice prefers tabs over spaces.")
    assert repo.retrieve_active("t1", "bob") == []


def test_get_memory_is_tenant_scoped(gateway, repo):
    _chat(gateway, "t1", "alice", "Remember Alice likes dark mode.")
    mem_id = repo.list_memories("t1", "alice")[0].id
    # Right scope returns it; wrong scope does not.
    assert repo.get_memory("t1", "alice", mem_id) is not None
    assert repo.get_memory("t1", "bob", mem_id) is None
    assert repo.get_memory("t2", "alice", mem_id) is None


def test_vector_search_is_tenant_and_user_scoped(gateway, repo):
    # The v0.3 vector candidate path must enforce isolation at the source.
    from app.embeddings import embed

    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    q = embed("roadmap")
    assert repo.search_candidates("tenant_demo", "user_demo", q) == []
    assert repo.search_candidates("tenant_acme", "other_user", q) == []
    assert repo.search_candidates("tenant_acme", "user_acme", q) != []


def test_loop_runs_are_tenant_and_user_scoped(gateway, repo):
    # The v0.3.1 loop engineering store records operational traces tagged by
    # tenant/user; those traces must not leak across the same boundary.
    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    assert repo.list_loop_runs(tenant_id="tenant_acme", user_id="user_acme") != []
    assert repo.list_loop_runs(tenant_id="tenant_demo") == []
    assert repo.list_loop_runs(tenant_id="tenant_acme", user_id="other_user") == []


def test_audit_listing_is_tenant_and_memory_scoped(gateway, repo):
    # v0.5: the control plane's per-memory audit filter must stay tenant-scoped
    # and must not surface another memory's events.
    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    mem_id = repo.list_memories("tenant_acme", "user_acme")[0].id

    # Cross-tenant audit read sees nothing.
    assert repo.list_audit("tenant_demo", "user_demo") == []
    # memory_id filter is scoped to that memory's events only.
    scoped = repo.list_audit("tenant_acme", "user_acme", memory_id=mem_id)
    assert scoped
    assert all(e.memory_id == mem_id for e in scoped)
    # A non-existent memory id yields no events.
    assert repo.list_audit("tenant_acme", "user_acme", memory_id="missing") == []
