"""v0.5 Memory Control Plane — governance API tests.

Covers list/detail/approve/reject/archive/restore/edit/delete plus provenance
and per-memory audit timeline, asserting the v0.5 safety rules: tenant scoping
(invariant #1), deletion guarantee (invariant #2), provenance (#3), and
auditability (#7).
"""

from __future__ import annotations

from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source, Status


def _seed(
    repo,
    *,
    status: Status = Status.active,
    tenant: str = "t1",
    user: str = "u1",
    content: str = "prefers dark mode dashboards",
) -> StoredMemory:
    m = StoredMemory(
        tenant_id=tenant,
        user_id=user,
        memory_type=MemoryType.preference,
        content=content,
        importance=5,
        confidence=0.8,
        sensitivity=Sensitivity.low,
        status=status,
        source=Source(kind="chat", excerpt=content),
    )
    return repo.create_memory(m)


def _q(tenant: str = "t1", user: str = "u1") -> str:
    return f"?tenant_id={tenant}&user_id={user}"


# ── list ──────────────────────────────────────────────────────────────────────
def test_list_excludes_deleted_and_is_tenant_scoped(api_client):
    client, repo = api_client
    keep = _seed(repo)
    _seed(repo, tenant="t2")  # other tenant
    gone = _seed(repo, status=Status.deleted, content="secret")

    r = client.get(f"/api/memories{_q()}")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()}
    assert keep.id in ids
    assert gone.id not in ids  # deletion guarantee
    assert all(m["tenant_id"] == "t1" for m in r.json())  # tenant isolation


def test_list_status_filter(api_client):
    client, repo = api_client
    _seed(repo, status=Status.active)
    pending = _seed(repo, status=Status.pending, content="needs approval")

    r = client.get(f"/api/memories{_q()}&status=pending")
    assert r.status_code == 200
    body = r.json()
    assert [m["id"] for m in body] == [pending.id]


# ── detail ────────────────────────────────────────────────────────────────────
def test_get_detail_and_404(api_client):
    client, repo = api_client
    m = _seed(repo)

    ok = client.get(f"/api/memories/{m.id}{_q()}")
    assert ok.status_code == 200
    assert ok.json()["content"] == m.content

    missing = client.get(f"/api/memories/does-not-exist{_q()}")
    assert missing.status_code == 404


def test_detail_is_tenant_scoped(api_client):
    client, repo = api_client
    m = _seed(repo)
    # Wrong tenant must not see it.
    assert client.get(f"/api/memories/{m.id}{_q(tenant='t2')}").status_code == 404


# ── approve / reject ───────────────────────────────────────────────────────────
def test_approve_pending(api_client):
    client, repo = api_client
    m = _seed(repo, status=Status.pending)

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "active"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    actions = {e.action for e in repo.list_audit("t1", "u1", memory_id=m.id)}
    assert "memory_approved" in actions


def test_reject_pending(api_client):
    client, repo = api_client
    m = _seed(repo, status=Status.pending)

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    actions = {e.action for e in repo.list_audit("t1", "u1", memory_id=m.id)}
    assert "memory_rejected" in actions


# ── archive / restore / edit ───────────────────────────────────────────────────
def test_archive_then_restore(api_client):
    client, repo = api_client
    m = _seed(repo)

    arch = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "archived"},
    )
    assert arch.json()["status"] == "archived"
    # Archived rows still appear in the inventory (only deleted is hidden), but
    # are filterable by status.
    listed = client.get(f"/api/memories{_q()}").json()
    assert m.id in {x["id"] for x in listed}
    archived_only = client.get(f"/api/memories{_q()}&status=archived").json()
    assert {x["id"] for x in archived_only} == {m.id}

    restored = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "active"},
    )
    assert restored.json()["status"] == "active"


def test_edit_content(api_client):
    client, repo = api_client
    m = _seed(repo)
    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "prefers light mode"},
    )
    assert r.status_code == 200
    assert r.json()["content"] == "prefers light mode"


# ── delete ─────────────────────────────────────────────────────────────────────
def test_delete_soft_hides_from_list_but_keeps_forensics(api_client):
    client, repo = api_client
    m = _seed(repo)

    d = client.request(
        "DELETE",
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1"},
    )
    assert d.status_code == 200
    assert d.json()["status"] == "deleted"

    # Never listed as active inventory ...
    listed = client.get(f"/api/memories{_q()}").json()
    assert m.id not in {x["id"] for x in listed}
    # ... but detail still reports it as deleted (governance forensics), never active.
    detail = client.get(f"/api/memories/{m.id}{_q()}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "deleted"


def test_delete_stamps_tombstone_lineage(api_client):
    # v1.4: the delete route stamps an explicit, audited tombstone marker so any
    # artifact derived from this memory is blocked from context (deletion
    # propagation via lineage, ADR-018).
    from app.db import lineage

    client, repo = api_client
    m = _seed(repo)

    d = client.request("DELETE", f"/api/memories/{m.id}",
                       json={"tenant_id": "t1", "user_id": "u1"})
    assert d.status_code == 200

    deleted = repo.get_memory("t1", "u1", m.id)
    assert deleted.status is Status.deleted
    assert lineage.is_tombstoned(deleted)


def test_delete_blocked_for_legal_hold_memory(api_client):
    """Legal hold (v0.10) is fail-closed: manual delete is refused with 409."""
    client, repo = api_client
    m = _seed(repo)

    held = client.post(
        "/api/retention/legal-hold",
        json={"tenant_id": "t1", "user_id": "u1", "memory_id": m.id, "on": True,
              "reason": "litigation"},
    )
    assert held.status_code == 200
    assert held.json()["governance"]["legal_hold"] is True

    blocked = client.request(
        "DELETE", f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1"},
    )
    assert blocked.status_code == 409
    # Still active (not deleted) and the blocked attempt is audited.
    assert repo.get_memory("t1", "u1", m.id).status == Status.active
    actions = {e.action for e in repo.list_audit("t1", "u1", memory_id=m.id)}
    assert "memory_legal_hold_delete_blocked" in actions

    # Releasing the hold allows deletion again.
    client.post(
        "/api/retention/legal-hold",
        json={"tenant_id": "t1", "user_id": "u1", "memory_id": m.id, "on": False},
    )
    ok = client.request(
        "DELETE", f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1"},
    )
    assert ok.status_code == 200


def test_cannot_patch_deleted_memory(api_client):
    client, repo = api_client
    m = _seed(repo, status=Status.deleted)
    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "active"},
    )
    assert r.status_code == 404  # deleted is terminal — cannot be reactivated


# ── provenance ─────────────────────────────────────────────────────────────────
def test_provenance_shape(api_client):
    client, repo = api_client
    m = _seed(repo)
    # generate an audited action so the trail is populated
    client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "archived"},
    )

    r = client.get(f"/api/memories/{m.id}/provenance{_q()}")
    assert r.status_code == 200
    body = r.json()
    assert body["memory_id"] == m.id
    assert body["source"]["kind"] == "chat"
    assert body["status"] == "archived"
    assert {"importance", "confidence", "weight", "reinforcement_count"} <= body.keys()
    assert len(body["audit_trail"]) >= 1
    # provenance must never leak embeddings/secrets
    assert "embedding" not in body


def test_provenance_404_for_unknown(api_client):
    client, _ = api_client
    assert client.get(f"/api/memories/nope/provenance{_q()}").status_code == 404


# ── per-memory audit timeline ──────────────────────────────────────────────────
def test_memory_audit_timeline_is_scoped_to_that_memory(api_client):
    client, repo = api_client
    a = _seed(repo, content="memory A")
    b = _seed(repo, content="memory B")

    client.patch(
        f"/api/memories/{a.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "archived"},
    )
    client.patch(
        f"/api/memories/{b.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "rejected"},
    )

    r = client.get(f"/api/memories/{a.id}/audit{_q()}")
    assert r.status_code == 200
    events = r.json()
    assert events  # non-empty
    assert all(e["memory_id"] == a.id for e in events)
    assert "memory_archived" in {e["action"] for e in events}
    assert "memory_rejected" not in {e["action"] for e in events}
