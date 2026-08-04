"""v0.5 Memory Control Plane — governance API tests.

Covers list/detail/approve/reject/archive/restore/edit/delete plus provenance
and per-memory audit timeline, asserting the v0.5 safety rules: tenant scoping
(invariant #1), deletion guarantee (invariant #2), provenance (#3), and
auditability (#7).
"""

from __future__ import annotations

import pytest

from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source, Status
from app.services.status_transitions import derive_patch_actions

from ._secret_fixtures import FAKE_PROVIDER_KEY


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


def test_approve_is_atomic_when_audit_fails(api_client, monkeypatch):
    """v2.3 (P0, ADR-027): the control-plane mutation + its audit event commit in one
    transaction. If the audit append fails while approving, the status change rolls
    back — the memory stays pending, never approved-without-evidence."""
    client, repo = api_client
    m = _seed(repo, status=Status.pending)

    def _boom(_event):
        raise RuntimeError("audit backend down")

    monkeypatch.setattr(repo, "add_audit", _boom)

    with pytest.raises(RuntimeError):
        client.patch(
            f"/api/memories/{m.id}",
            json={"tenant_id": "t1", "user_id": "u1", "status": "active"},
        )

    # Rolled back: still pending, and no partial audit event for the approval.
    assert repo.get_memory("t1", "u1", m.id).status is Status.pending
    assert repo.list_audit("t1", "u1", memory_id=m.id) == []


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
    # B is seeded `pending` so its rejection is a *legal* transition and actually
    # writes a `memory_rejected` event. Seeded active, the reject is refused (409)
    # and this test would pass vacuously — proving isolation of an event that was
    # never written.
    b = _seed(repo, status=Status.pending, content="memory B")

    archived = client.patch(
        f"/api/memories/{a.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "archived"},
    )
    assert archived.status_code == 200
    rejected = client.patch(
        f"/api/memories/{b.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "rejected"},
    )
    assert rejected.status_code == 200

    # The event exists on B, so its absence from A's timeline is meaningful.
    b_actions = {e["action"] for e in client.get(f"/api/memories/{b.id}/audit{_q()}").json()}
    assert "memory_rejected" in b_actions

    r = client.get(f"/api/memories/{a.id}/audit{_q()}")
    assert r.status_code == 200
    events = r.json()
    assert events  # non-empty
    assert all(e["memory_id"] == a.id for e in events)
    assert "memory_archived" in {e["action"] for e in events}
    assert "memory_rejected" not in {e["action"] for e in events}


def test_content_edit_goes_through_governance(api_client):
    """The governance API's edit path is no longer a direct assignment.

    Full coverage in tests/test_governed_content_update.py; this pins the API
    surface: a credential edit is refused and the memory is left untouched, and a
    benign edit bumps the revision returned to the client.
    """
    client, repo = api_client
    m = _seed(repo, content="prefers dark mode")

    blocked = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": FAKE_PROVIDER_KEY},
    )
    assert blocked.status_code == 422
    assert repo.get_memory("t1", "u1", m.id).content == "prefers dark mode"

    ok = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "prefers light mode"},
    )
    assert ok.status_code == 200
    assert ok.json()["content"] == "prefers light mode"
    assert ok.json()["revision"] == 2


# ── one patch, every action it requests (v2.4) ───────────────────────────────
def test_approving_and_editing_in_one_patch_is_two_governance_actions(api_client):
    """`{"content": ..., "status": "active"}` approves *and* rewrites.

    The route resolves it to a single audit action today, which is the reason
    authorization cannot key off the status transition alone: whoever may approve
    would implicitly be allowed to rewrite the text they are approving, in the
    request that approves it, leaving only the approval in the trail. Pinned here
    so the coupling is visible while the route is still `planned`.
    """
    client, repo = api_client
    m = _seed(repo, status=Status.pending, content="original claim")

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "rewritten claim", "status": "active"},
    )
    assert r.status_code == 200, r.text

    stored = repo.get_memory("t1", "u1", m.id)
    assert stored.status is Status.active
    assert stored.content == "rewritten claim"

    actions = derive_patch_actions(
        has_content=True,
        has_importance=False,
        has_confidence=False,
        transition="approve",
    )
    assert actions == {"edit", "approve"}, (
        "both permissions must be required once this route is enforced"
    )


def test_a_patch_requesting_no_change_is_refused(api_client):
    """It returned 200 with the record and wrote a `memory_updated` audit event
    for a mutation that never happened — a no-op indistinguishable from an edit."""
    client, repo = api_client
    m = _seed(repo)
    audit_before = len(client.get(f"/api/audit{_q()}").json())

    r = client.patch(f"/api/memories/{m.id}", json={"tenant_id": "t1", "user_id": "u1"})
    assert r.status_code == 422
    assert "no change" in r.json()["detail"]
    assert len(client.get(f"/api/audit{_q()}").json()) == audit_before


def test_every_single_field_patch_still_works(api_client):
    """The 422 must catch only genuinely empty bodies."""
    client, repo = api_client
    for field, value in (("content", "new text"), ("importance", 9), ("confidence", 0.4)):
        m = _seed(repo)
        r = client.patch(
            f"/api/memories/{m.id}", json={"tenant_id": "t1", "user_id": "u1", field: value}
        )
        assert r.status_code == 200, f"{field}: {r.text}"

    pending = _seed(repo, status=Status.pending)
    r = client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "active"},
    )
    assert r.status_code == 200, r.text


def test_a_mixed_patch_writes_one_record_per_action(api_client):
    """v2.4: the mixed case no longer collapses into a single audit record.

    With auth disabled there is no principal to authorize, so this is purely about
    the *evidence*: an edit bundled with an approval used to leave a trail naming
    only the approval, because the transition overwrote the edit's action and reason.
    """
    client, repo = api_client
    m = _seed(repo, status=Status.pending, content="original claim")
    before = len(repo.list_audit("t1", "u1", memory_id=m.id, limit=50))

    r = client.patch(
        f"/api/memories/{m.id}",
        json={"tenant_id": "t1", "user_id": "u1", "content": "corrected claim",
              "status": "active"},
    )
    assert r.status_code == 200, r.text

    rows = repo.list_audit("t1", "u1", memory_id=m.id, limit=50)
    assert len(rows) == before + 2, [row.action for row in rows]
    actions = {row.action for row in rows}
    assert "memory_approved" in actions
    assert actions & {"memory_updated", "memory_content_updated"}, actions

    for row in rows:
        if row.action == "memory_approved":
            assert row.metadata["requested_actions"] == ["approve", "edit"]
            assert row.metadata["content_updated"] is True
            assert row.metadata["transition"] == "approve"
            break
    else:
        pytest.fail("no memory_approved record")


def test_single_action_patches_still_write_exactly_one_record(api_client):
    """The fix must not double every ordinary patch."""
    client, repo = api_client
    for body in (
        {"content": "just an edit"},
        {"importance": 8},
        {"confidence": 0.55},
    ):
        m = _seed(repo)
        before = len(repo.list_audit("t1", "u1", memory_id=m.id, limit=50))
        r = client.patch(f"/api/memories/{m.id}", json={"tenant_id": "t1", "user_id": "u1", **body})
        assert r.status_code == 200, r.text
        after = repo.list_audit("t1", "u1", memory_id=m.id, limit=50)
        assert len(after) == before + 1, (body, [row.action for row in after])

    pending = _seed(repo, status=Status.pending)
    before = len(repo.list_audit("t1", "u1", memory_id=pending.id, limit=50))
    r = client.patch(
        f"/api/memories/{pending.id}", json={"tenant_id": "t1", "user_id": "u1", "status": "active"}
    )
    assert r.status_code == 200
    after = repo.list_audit("t1", "u1", memory_id=pending.id, limit=50)
    assert len(after) == before + 1
    assert after[0].action == "memory_approved"


def test_governance_transitions_are_unchanged_with_auth_disabled(api_client):
    """The development default. Enforcement must not have changed what works here."""
    client, repo = api_client
    pending = _seed(repo, status=Status.pending)
    assert client.patch(
        f"/api/memories/{pending.id}", json={"tenant_id": "t1", "user_id": "u1", "status": "active"}
    ).status_code == 200

    active = _seed(repo)
    assert client.patch(
        f"/api/memories/{active.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "archived"},
    ).status_code == 200
    assert client.patch(
        f"/api/memories/{active.id}", json={"tenant_id": "t1", "user_id": "u1", "status": "active"}
    ).status_code == 200

    rejectable = _seed(repo, status=Status.pending)
    assert client.patch(
        f"/api/memories/{rejectable.id}",
        json={"tenant_id": "t1", "user_id": "u1", "status": "rejected"},
    ).status_code == 200
