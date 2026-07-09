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


def test_compaction_listing_is_tenant_scoped(gateway, repo):
    # v0.7: the compaction worker's source query (list_deleted_for_compaction)
    # and the compaction mutation must stay within the (tenant, user) scope.
    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    mem = repo.list_memories("tenant_acme", "user_acme")[0]
    repo.soft_delete("tenant_acme", "user_acme", mem.id)

    # Another tenant sees no deleted-for-compaction rows and cannot compact it.
    assert repo.list_deleted_for_compaction("tenant_demo", "user_demo") == []
    assert repo.compact_deleted_memory("tenant_demo", "user_demo", mem.id, reason="x") is None
    # Wrong user in the same tenant also cannot reach it.
    assert repo.compact_deleted_memory("tenant_acme", "other_user", mem.id, reason="x") is None
    # The correct scope sees exactly its one deleted row.
    assert [m.id for m in repo.list_deleted_for_compaction("tenant_acme", "user_acme")] == [mem.id]


def test_worker_runs_are_tenant_scoped(repo):
    # v0.8: worker run history is operational evidence tagged by tenant/user and
    # must filter to a single scope (no cross-tenant leakage of run records).
    from app.db.entities import WorkerRunRecord

    repo.add_worker_run(WorkerRunRecord(tenant_id="tenant_acme", user_id="u1", status="completed"))
    repo.add_worker_run(WorkerRunRecord(tenant_id="tenant_demo", user_id="u1", status="completed"))

    acme = repo.list_worker_runs(tenant_id="tenant_acme")
    assert [r.tenant_id for r in acme] == ["tenant_acme"]
    assert repo.list_worker_runs(tenant_id="tenant_demo", user_id="other") == []


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


def test_lineage_ancestry_lookup_is_tenant_scoped(gateway, repo):
    # v1.4: tombstone-lineage ancestry is resolved through a tenant/user-scoped
    # lookup. A derived memory in one tenant that references an id living in
    # another tenant must NOT resolve cross-tenant — the ancestor reads as missing
    # and the derived artifact is blocked fail-closed (no cross-tenant leakage).
    from app.db import lineage
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    _chat(gateway, "t2", "bob", "Remember Bob prefers Vendor Z.")
    foreign_parent = repo.list_memories("t2", "bob")[0]

    derived = StoredMemory(
        tenant_id="t1", user_id="alice", memory_type=MemoryType.semantic,
        content="summary derived from a foreign-tenant id", importance=6,
        confidence=0.9, sensitivity=Sensitivity.low, status=Status.active,
        source=Source(kind="reflection"),
    )
    lineage.set_lineage(derived, parent_ids=[foreign_parent.id])
    repo.create_memory(derived)

    # Scoped resolver for tenant t1/alice cannot see t2/bob's row → missing → block.
    def scoped_lookup(mid):
        return repo.get_memory("t1", "alice", mid)

    assert lineage.ancestry_tombstone(derived, scoped_lookup) == foreign_parent.id


def test_governance_flags_are_tenant_scoped(gateway, repo):
    # v0.10: setting a legal hold on one tenant's memory must not affect another
    # tenant's memory, and update_memory persists governance metadata in scope.
    from app.db import governance as gov

    _chat(gateway, "t1", "alice", "Remember Alice prefers tabs.")
    _chat(gateway, "t2", "bob", "Remember Bob prefers spaces.")
    a = repo.list_memories("t1", "alice")[0]
    b = repo.list_memories("t2", "bob")[0]

    gov.set_legal_hold(a, on=True, reason="hold")
    repo.update_memory(a)

    # Persisted in scope ...
    assert gov.is_legal_hold(repo.get_memory("t1", "alice", a.id))
    # ... and never leaks to the other tenant.
    assert not gov.is_legal_hold(repo.get_memory("t2", "bob", b.id))
    # Wrong-scope read cannot see the held memory at all.
    assert repo.get_memory("t2", "bob", a.id) is None
