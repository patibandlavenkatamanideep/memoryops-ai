"""`PATCH /api/memories/{id}` must not bypass the deletion workflow.

The exploit
-----------
`MemoryPatch.status` accepted the entire `Status` enum and the handler assigned it
directly; its `elif` chain only named active/rejected/archived, so anything else
fell through and was written verbatim. `status="deleted"` produced a row that was:

  * hidden from retrieval (invariant #2 excludes `deleted`),
  * but with `deleted_at = None`, so retention and compaction — which key off
    `deleted_at` — never reclaimed it,
  * with no tombstone and no lineage propagation,
  * audited only as a generic `memory_updated`,
  * **and it succeeded under a legal hold** that the real `DELETE` route refuses
    with 409.

The record landed in a limbo neither guarantee covers: invisible to the user,
un-compactable by the system, and still reported as held. A *preservation* control
defeated by a route that was not even trying to delete.

Deletion stays exclusive to `DELETE /api/memories/{memory_id}` — the only path that
performs legal-hold verification, `deleted_at` assignment, tombstone creation,
lineage propagation, deletion audit evidence, and compaction eligibility.
"""

from __future__ import annotations

import pytest

from app.db import lineage
from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source, Status

_Q = "?tenant_id=t1&user_id=u1"


def _seed(repo, *, status: Status = Status.active, content: str = "dark mode") -> StoredMemory:
    return repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content=content,
            importance=7,
            confidence=0.9,
            sensitivity=Sensitivity.low,
            status=status,
            source=Source(kind="chat", excerpt=content),
        )
    )


def _patch(client, memory_id: str, **fields):
    return client.patch(
        f"/api/memories/{memory_id}",
        json={"tenant_id": "t1", "user_id": "u1", **fields},
    )


# ── the exploit, as a permanent regression test ──────────────────────────────
def test_legal_hold_cannot_be_bypassed_by_patching_status_to_deleted(api_client):
    client, repo = api_client

    # 1. an active memory
    m = _seed(repo, content="my account number is 12345")
    assert repo.get_memory("t1", "u1", m.id).status is Status.active

    # 2. under legal hold
    hold = client.post(
        "/api/retention/legal-hold",
        json={
            "tenant_id": "t1",
            "user_id": "u1",
            "memory_id": m.id,
            "on": True,
            "reason": "litigation",
        },
    )
    assert hold.status_code == 200

    # 3. the real deletion route correctly refuses
    deleted = client.request(
        "DELETE", f"/api/memories/{m.id}", json={"tenant_id": "t1", "user_id": "u1"}
    )
    assert deleted.status_code == 409, "legal hold must block the deletion workflow"

    # 4. and PATCH must not be a way around it
    bypass = _patch(client, m.id, status="deleted")
    assert bypass.status_code == 422, (
        "PATCH status=deleted must be refused; it previously succeeded with 200 and "
        "produced a row hidden from retrieval but with no deleted_at, no tombstone, "
        "and no deletion audit — while still under legal hold"
    )

    # 5. the memory is untouched and still active
    after = repo.get_memory("t1", "u1", m.id)
    assert after.status is Status.active

    # 6. no deletion timestamp was stamped
    assert after.deleted_at is None

    # 7. no tombstone was created
    #    `is_tombstoned` is true for an explicit marker OR a soft-deleted row, so
    #    this covers both the marker and the status the bypass used to set.
    assert not lineage.is_tombstoned(after)

    # 8. governance still reports the hold
    state = client.get(f"/api/retention/memory/{m.id}{_Q}").json()
    assert state["governance"]["legal_hold"] is True
    assert state["retention_decision"]["eligible_for_deletion"] is False

    # 9. no deletion audit event exists
    actions = {e["action"] for e in client.get(f"/api/memories/{m.id}/audit{_Q}").json()}
    assert "memory_deleted" not in actions

    # 10. and no generic update event falsely stands in for a deletion
    assert "memory_updated" not in actions, (
        "the refused transition must not be audited as an edit"
    )


def test_patch_status_deleted_is_refused_even_without_a_legal_hold(api_client):
    """The bypass is invalid on its own terms, not only when a hold exists."""
    client, repo = api_client
    m = _seed(repo)

    assert _patch(client, m.id, status="deleted").status_code == 422
    after = repo.get_memory("t1", "u1", m.id)
    assert after.status is Status.active
    assert after.deleted_at is None


def test_the_deletion_route_still_works_without_a_hold(api_client):
    """Closing the bypass must not break legitimate deletion."""
    client, repo = api_client
    m = _seed(repo)

    r = client.request(
        "DELETE", f"/api/memories/{m.id}", json={"tenant_id": "t1", "user_id": "u1"}
    )
    assert r.status_code == 200
    after = repo.get_memory("t1", "u1", m.id)
    assert after.status is Status.deleted
    assert after.deleted_at is not None, "the real workflow stamps deleted_at"


# ── unsupported target statuses (422) ────────────────────────────────────────
@pytest.mark.parametrize("target", ["deleted", "pending", "blocked"])
def test_unsupported_statuses_are_rejected_with_422(api_client, target):
    client, repo = api_client
    m = _seed(repo)
    r = _patch(client, m.id, status=target)
    assert r.status_code == 422, f"PATCH status={target} must be unsupported"
    assert repo.get_memory("t1", "u1", m.id).status is Status.active


# ── invalid current-state transitions (409) ──────────────────────────────────
@pytest.mark.parametrize(
    ("current", "target"),
    [
        (Status.active, "rejected"),  # rejection is only for pending memory
        (Status.active, "active"),  # no-op is not a governance transition
        (Status.pending, "archived"),  # must be approved before it can be archived
        (Status.archived, "rejected"),
        (Status.rejected, "active"),
        (Status.rejected, "archived"),
    ],
)
def test_invalid_transitions_are_rejected_with_409(api_client, current, target):
    client, repo = api_client
    m = _seed(repo, status=current)
    r = _patch(client, m.id, status=target)
    assert r.status_code == 409, f"{current.value} -> {target} must be refused"
    assert repo.get_memory("t1", "u1", m.id).status is current


def test_deleted_memory_cannot_be_patched_to_any_status(api_client):
    """Deleted is terminal — the route 404s before any transition check."""
    client, repo = api_client
    m = _seed(repo, status=Status.deleted)
    for target in ("active", "archived", "rejected"):
        assert _patch(client, m.id, status=target).status_code == 404


# ── the four legal transitions still work ────────────────────────────────────
@pytest.mark.parametrize(
    ("current", "target", "audit_action"),
    [
        (Status.pending, "active", "memory_approved"),
        (Status.pending, "rejected", "memory_rejected"),
        (Status.active, "archived", "memory_archived"),
        (Status.archived, "active", "memory_restored"),
    ],
)
def test_legal_transitions_succeed_and_audit_the_right_action(
    api_client, current, target, audit_action
):
    client, repo = api_client
    m = _seed(repo, status=current)

    r = _patch(client, m.id, status=target)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == target
    assert repo.get_memory("t1", "u1", m.id).status.value == target

    actions = {e["action"] for e in client.get(f"/api/memories/{m.id}/audit{_Q}").json()}
    assert audit_action in actions


def test_restore_is_audited_distinctly_from_approve(api_client):
    """The old handler keyed the audit action off the *target* alone, so
    pending→active and archived→active were both 'memory_approved' — a restore was
    indistinguishable from an approval in the audit trail."""
    client, repo = api_client
    restored = _seed(repo, status=Status.archived, content="was archived")

    assert _patch(client, restored.id, status="active").status_code == 200
    actions = {e["action"] for e in client.get(f"/api/memories/{restored.id}/audit{_Q}").json()}
    assert "memory_restored" in actions
    assert "memory_approved" not in actions


# ── compatibility: the field and the content path are unchanged ──────────────
def test_status_field_is_still_accepted_in_the_request_shape(api_client):
    """This is a behavioural correction for invalid transitions, not a field removal
    — the 1.x additive-compatibility promise holds."""
    client, repo = api_client
    m = _seed(repo, status=Status.pending)
    assert _patch(client, m.id, status="active").status_code == 200


def test_content_only_patch_is_unaffected(api_client):
    client, repo = api_client
    m = _seed(repo)
    r = _patch(client, m.id, content="prefers light mode")
    assert r.status_code == 200
    assert r.json()["content"] == "prefers light mode"
    assert repo.get_memory("t1", "u1", m.id).status is Status.active


# ── a patch that asks for nothing ────────────────────────────────────────────
def test_a_patch_with_no_changed_field_is_refused(api_client):
    """It returned 200 and a full memory record while requesting no change.

    That matters once the route is authorized: a body with no action has no
    permission to check against, so it would be a request nothing authorized that
    still succeeded — and in the audit trail it is indistinguishable from a real
    edit, because it opens a governance loop run and writes a `memory_updated`
    event for a mutation that never happened.
    """
    client, repo = api_client
    m = _seed(repo)
    before = repo.get_memory("t1", "u1", m.id)
    revision_before = before.revision

    r = _patch(client, m.id)
    assert r.status_code == 422
    assert "no change" in r.json()["detail"]

    after = repo.get_memory("t1", "u1", m.id)
    assert after.revision == revision_before, "a refused patch must not bump revision"


def test_a_revision_guard_alone_is_still_no_change(api_client):
    client, repo = api_client
    m = _seed(repo)
    r = _patch(client, m.id, expected_revision=repo.get_memory("t1", "u1", m.id).revision)
    assert r.status_code == 422


def test_the_refusal_happens_before_any_governance_evidence_is_written(api_client):
    """No loop run, no audit event. A rejected request must leave no trace that
    reads like a completed governance action."""
    client, repo = api_client
    m = _seed(repo)
    audit_before = len(client.get(f"/api/audit{_Q}").json())
    runs_before = len(client.get(f"/api/loops/runs{_Q}").json())

    assert _patch(client, m.id).status_code == 422

    assert len(client.get(f"/api/audit{_Q}").json()) == audit_before
    assert len(client.get(f"/api/loops/runs{_Q}").json()) == runs_before


def test_a_nonexistent_memory_still_reports_the_empty_patch(api_client):
    """The emptiness check runs before the lookup, so it cannot be used to probe
    which memory ids exist."""
    client, _repo = api_client
    assert _patch(client, "does-not-exist").status_code == 422
