"""Tenant isolation (invariant #1): no cross-tenant / cross-user retrieval."""

from __future__ import annotations

from app.db.entities import StoredMemory
from app.schemas.memory import ChatRequest, MemoryType, Sensitivity, Source, Status


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


def test_vector_index_seam_preserves_isolation_and_deletion(gateway, repo):
    # v1.7: similarity now flows through the pluggable VectorIndex. The seam must
    # not weaken isolation or deletion — a query only sees its own scope, and a
    # soft-deleted memory's vector is removed so it can never be a candidate again.
    from app.embeddings import embed

    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    q = embed("roadmap")

    # Isolation through the index: other tenant / other user see nothing.
    assert repo.search_candidates("tenant_demo", "user_demo", q) == []
    assert repo.search_candidates("tenant_acme", "other_user", q) == []
    hit = repo.search_candidates("tenant_acme", "user_acme", q)
    assert hit and hit[0][1] > 0.0

    # Deletion through the index: after soft-delete the vector is gone.
    mem_id = repo.list_memories("tenant_acme", "user_acme")[0].id
    repo.soft_delete("tenant_acme", "user_acme", mem_id)
    assert repo.search_candidates("tenant_acme", "user_acme", q) == []


def test_loop_runs_are_tenant_and_user_scoped(gateway, repo):
    # The v0.3.1 loop engineering store records operational traces tagged by
    # tenant/user; those traces must not leak across the same boundary.
    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    assert repo.list_loop_runs(tenant_id="tenant_acme", user_id="user_acme") != []
    assert repo.list_loop_runs(tenant_id="tenant_demo") == []
    assert repo.list_loop_runs(tenant_id="tenant_acme", user_id="other_user") == []


def test_audit_hash_chain_is_per_tenant(gateway, repo):
    # v2.0 (ADR-024): the tamper-evident audit chain is per-tenant, so one tenant's
    # events never link into another's and each chain verifies independently.
    from app.evidence.reports import verify_audit

    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme prefers Vendor A.")
    _chat(gateway, "tenant_demo", "user_demo", "Remember Demo prefers Vendor B.")
    acme = repo.list_audit("tenant_acme", limit=1000)
    demo = repo.list_audit("tenant_demo", limit=1000)
    assert acme and demo
    # No cross-tenant leakage into either chain, and both verify.
    assert all(e.tenant_id == "tenant_acme" for e in acme)
    assert verify_audit(repo, "tenant_acme")["ok"] and verify_audit(repo, "tenant_demo")["ok"]


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


def test_worker_health_operational_read_is_explicitly_cross_tenant(repo):
    # v2.3 (P0): global worker health is a deliberate cross-tenant *operational*
    # view, kept on a separate, explicitly-authorized path — never by relaxing the
    # tenant-scoped query (which stays isolated, asserted above). The two methods
    # answer different questions and must not be confused.
    from app.db.entities import WorkerRunRecord

    repo.add_worker_run(WorkerRunRecord(tenant_id="tenant_acme", user_id="u1", status="completed"))
    repo.add_worker_run(WorkerRunRecord(tenant_id="tenant_demo", user_id="u1", status="failed"))

    # Tenant-scoped read still refuses to span tenants.
    assert {r.tenant_id for r in repo.list_worker_runs(tenant_id="tenant_acme")} == {"tenant_acme"}
    # The operational read is the *only* one that spans them, and it is opt-in.
    operational = repo.list_worker_runs_operational()
    assert {r.tenant_id for r in operational} == {"tenant_acme", "tenant_demo"}


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


def test_governed_content_update_cannot_reach_another_tenant(api_client):
    """The edit path is tenant-scoped like every other repository access (#1).

    The governed update service reads and writes through `repo.get_memory` /
    `repo.update_memory`, both tenant+user scoped, so a caller cannot edit — or
    learn the existence of — another tenant's memory.
    """
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    victim = repo.create_memory(
        StoredMemory(
            tenant_id="victim",
            user_id="v1",
            memory_type=MemoryType.preference,
            content="victim secret preference",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="victim secret preference"),
        )
    )

    r = client.patch(
        f"/api/memories/{victim.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "overwritten by attacker"},
    )
    assert r.status_code == 404, "another tenant's memory must not be addressable"
    assert repo.get_memory("victim", "v1", victim.id).content == "victim secret preference"


def test_revision_is_not_a_cross_tenant_oracle(api_client):
    """A stale-revision 409 must not distinguish 'wrong revision' from 'not yours'."""
    from app.db.entities import StoredMemory
    from app.schemas.memory import MemoryType, Sensitivity, Source, Status

    client, repo = api_client
    victim = repo.create_memory(
        StoredMemory(
            tenant_id="victim",
            user_id="v1",
            memory_type=MemoryType.preference,
            content="victim preference",
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="chat", excerpt="victim preference"),
        )
    )
    r = client.patch(
        f"/api/memories/{victim.id}",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "content": "probe",
            "expected_revision": 1,
        },
    )
    # 404 (not 409): scope is checked before the revision, so the response is
    # identical whether or not the revision would have matched.
    assert r.status_code == 404


# ── the authorization lookup (v2.4) ──────────────────────────────────────────
def test_get_memory_in_tenant_never_crosses_a_tenant(gateway, repo):
    """Ownership authorization needs a record it can inspect *before* it knows the
    owner — so it cannot pass `user_id` as a filter, and a naive implementation
    reaches for a global lookup by id with the tenant checked afterward.

    That shape is one dropped condition away from a cross-tenant read, and it reads
    as safe because the comparison is right there. The tenant stays a predicate.
    """
    _chat(gateway, "tenant_acme", "user_acme", "Remember Acme's roadmap is confidential.")
    mem_id = repo.list_memories("tenant_acme", "user_acme")[0].id

    assert repo.get_memory_in_tenant("tenant_acme", mem_id) is not None
    assert repo.get_memory_in_tenant("tenant_demo", mem_id) is None
    assert repo.get_memory_in_tenant("", mem_id) is None


def test_get_memory_in_tenant_spans_users_but_only_inside_the_tenant(gateway, repo):
    """It must see another user's record — that is the point; a per-user lookup
    could not tell "not yours" apart from "does not exist", and the route needs the
    owner to decide which permission applies. The tenant boundary still holds.
    """
    _chat(gateway, "t1", "alice", "Remember Alice likes dark mode.")
    mem_id = repo.list_memories("t1", "alice")[0].id

    found = repo.get_memory_in_tenant("t1", mem_id)
    assert found is not None and found.user_id == "alice"
    # Same id, other tenant: nothing.
    assert repo.get_memory_in_tenant("t2", mem_id) is None


def test_a_deleted_memory_is_not_exposed_through_the_authorization_lookup(api_client):
    """The lookup deliberately returns a soft-deleted row so authorization can run
    on it, so the deletion guarantee (invariant #2) has to be re-proved at the
    route: nothing about a deleted memory may reach a response through this path.
    """
    client, repo = api_client
    content = "the quarterly rotation date is the 3rd"
    mem_id = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content=content,
            importance=6,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=Status.active,
            source=Source(kind="manual", excerpt=content),
        )
    ).id
    deleted = client.request(
        "DELETE",
        f"/api/memories/{mem_id}",
        json={"tenant_id": "t1", "user_id": "u1"},
    )
    assert deleted.status_code == 200, deleted.text

    # The repository still hands it to the authorization layer...
    stored = repo.get_memory_in_tenant("t1", mem_id)
    assert stored is not None and stored.status is Status.deleted

    # ...and the mutation route must not act on it.
    patched = client.patch(
        f"/api/memories/{mem_id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "rewritten"},
    )
    assert patched.status_code == 404
    assert content not in patched.text
    assert repo.get_memory_in_tenant("t1", mem_id).content != "rewritten"

    # It is still absent from retrieval, which is what invariant #2 governs.
    assert repo.retrieve_active("t1", "u1") == []
    assert [m.id for m in repo.list_memories("t1", "u1")] == []

    # The control-plane detail route is a deliberate exception: it returns
    # soft-deleted rows for governance/forensics, carrying the true `status`
    # rather than concealing them. Pinned so the exception stays explicit.
    detail = client.get(f"/api/memories/{mem_id}?tenant_id=t1&user_id=u1")
    assert detail.status_code == 200
    assert detail.json()["status"] == "deleted"
