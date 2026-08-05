"""Authorization on the seven memory routes, and proof the checks actually run.

Why a separate file
-------------------
`test_api_rbac.py` proves the role model. This proves the *routes*: that each one
consults it, on the right record, in the right order, and leaves nothing behind when
it refuses.

Three things are asserted together for every enforced route, because any two can pass
while the control is broken:

  1. an authorized caller succeeds,
  2. an unauthorized caller is refused,
  3. the expected helper ran, with the expected permission and self/tenant branch.

(1) and (2) can both hold by accident — a handler that stopped checking still answers
correctly for a caller who happens to be permitted, and a 404 for the wrong reason
looks identical from outside. (3) is the evidence that the check itself executed.
"""

from __future__ import annotations

import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.authz_spec import ROUTE_AUTHZ, Status
from app.auth.witness import witness_for
from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source
from app.schemas.memory import Status as MemStatus

from ._secret_fixtures import FAKE_JWT_SIGNING_KEY

TENANT = "acme"


def _hdr(user: str, roles: str | None = None, tenant: str = TENANT) -> dict:
    h = {"X-MemoryOps-Tenant": tenant, "X-MemoryOps-User": user}
    if roles:
        h["X-MemoryOps-Roles"] = roles
    return h


@pytest.fixture
def authz(monkeypatch):
    """Trusted-header auth, an in-memory store, and a witness recorder.

    The recorder is a middleware rather than a monkeypatch of the helpers: it observes
    what the real request actually did. Patching the helpers would make the evidence
    a product of the test rather than of the code.
    """
    from app import deps
    from app.core import config
    from app.db import factory

    def _clear():
        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()

    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "trusted_header")
    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    _clear()
    from fastapi.testclient import TestClient

    from app.main import app

    recorded: list = []

    async def _capture(request, call_next):
        response = await call_next(request)
        recorded.extend(witness_for(request).decisions)
        return response

    # `app` is a module-level singleton another test may already have started, and
    # Starlette refuses new middleware once the stack is built. Dropping the built
    # stack forces a rebuild that includes ours; the teardown below removes it again
    # so no other module inherits a listener.
    app.middleware_stack = None
    app.add_middleware(BaseHTTPMiddleware, dispatch=_capture)

    client = TestClient(app)
    repo = factory.get_repository()

    class Harness:
        def __init__(self):
            self.client = client
            self.repo = repo
            self.decisions = recorded

        def seed(self, *, user="alice", status=MemStatus.active, content="prefers dark mode"):
            return repo.create_memory(
                StoredMemory(
                    tenant_id=TENANT,
                    user_id=user,
                    memory_type=MemoryType.preference,
                    content=content,
                    importance=5,
                    confidence=0.8,
                    sensitivity=Sensitivity.low,
                    status=status,
                    source=Source(kind="chat", excerpt=content),
                )
            )

        def last_for(self, method, path):
            return [d for d in recorded if d.route == (method, path)]

        def clear(self):
            recorded.clear()

    yield Harness()
    # Starlette keeps user middleware on the app object; drop ours so it cannot leak
    # into another test's app instance.
    app.user_middleware = [
        m for m in app.user_middleware if m.kwargs.get("dispatch") is not _capture
    ]
    app.middleware_stack = None
    _clear()


# ── the witness gate: every ENFORCED memory route proves a check ran ──────────
def _drive_every_enforced_memory_route(h) -> set[tuple[str, str]]:
    """One authorized request per enforced memory route. Returns the routes driven."""
    admin = _hdr("alice", "memory_admin auditor")
    mem = h.seed()
    pending = h.seed(status=MemStatus.pending, content="claims the launch is in May")
    doomed = h.seed(content="temporary note")
    q = f"?tenant_id={TENANT}&user_id=alice"

    assert h.client.post(
        "/api/chat",
        json={"tenant_id": TENANT, "user_id": "alice", "message": "hello"},
        headers=admin,
    ).status_code == 200
    assert h.client.get(f"/api/memories{q}", headers=admin).status_code == 200
    assert h.client.get(f"/api/memories/{mem.id}{q}", headers=admin).status_code == 200
    assert h.client.get(f"/api/memories/{mem.id}/audit{q}", headers=admin).status_code == 200
    assert h.client.get(f"/api/memories/{mem.id}/provenance{q}", headers=admin).status_code == 200
    assert h.client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "status": "active"},
        headers=admin,
    ).status_code == 200
    assert h.client.request(
        "DELETE",
        f"/api/memories/{doomed.id}",
        json={"tenant_id": TENANT, "user_id": "alice"},
        headers=admin,
    ).status_code == 200

    return {
        ("POST", "/api/chat"),
        ("GET", "/api/memories"),
        ("GET", "/api/memories/{memory_id}"),
        ("GET", "/api/memories/{memory_id}/audit"),
        ("GET", "/api/memories/{memory_id}/provenance"),
        ("PATCH", "/api/memories/{memory_id}"),
        ("DELETE", "/api/memories/{memory_id}"),
    }


def test_every_enforced_memory_route_records_an_authorization_decision(authz):
    """The gate that makes ENFORCED mean something.

    Not a second hand-maintained list checked against the first — that only proves
    two lists agree. Each route is *driven* and its witness read back, so a handler
    that stopped calling the helper fails here even though it still returns 200 for
    this (authorized) caller.
    """
    driven = _drive_every_enforced_memory_route(authz)

    enforced_memory_routes = {
        (m, p)
        for (m, p), spec in ROUTE_AUTHZ.items()
        if spec.status is Status.ENFORCED and (p.startswith("/api/memories") or p == "/api/chat")
    }
    assert driven == enforced_memory_routes, (
        "an enforced memory route is not exercised by the witness gate: "
        f"{sorted(driven ^ enforced_memory_routes)}"
    )

    witnessed = {d.route for d in authz.decisions}
    missing = enforced_memory_routes - witnessed
    assert not missing, f"enforced but no authorization decision recorded: {sorted(missing)}"


def test_the_witness_gate_fails_when_a_route_stops_checking(authz, monkeypatch):
    """Proves the gate above is not vacuous.

    With the helper neutered the requests still succeed — which is the whole point:
    a broken control is invisible in the status code.
    """
    import app.routes.memories as memories_route
    from app.auth.decisions import AuthorizedSubject

    monkeypatch.setattr(
        memories_route,
        "authorize_subject_scope",
        lambda request, **kw: AuthorizedSubject(
            kw["requested_tenant_id"], kw["requested_user_id"], False
        ),
    )
    authz.clear()
    r = authz.client.get(
        f"/api/memories?tenant_id={TENANT}&user_id=alice", headers=_hdr("alice")
    )
    assert r.status_code == 200, "the neutered handler still answers normally"
    assert not authz.last_for("GET", "/api/memories"), (
        "no decision should have been recorded — if one was, the gate cannot detect "
        "a handler that stopped checking"
    )


# ── per-route semantics ──────────────────────────────────────────────────────
def test_a_viewer_reads_its_own_memory_but_cannot_mutate_it(authz):
    mem = authz.seed()
    q = f"?tenant_id={TENANT}&user_id=alice"
    viewer = _hdr("alice", "memory_viewer")

    assert authz.client.get(f"/api/memories/{mem.id}{q}", headers=viewer).status_code == 200
    decision = authz.last_for("GET", "/api/memories/{memory_id}")[-1]
    assert decision.permission.value == "memory:read:self"
    assert decision.tenant_scoped is False

    assert authz.client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "content": "rewritten"},
        headers=viewer,
    ).status_code == 403
    assert authz.client.request(
        "DELETE",
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice"},
        headers=viewer,
    ).status_code == 403


def test_a_memory_user_manages_and_deletes_its_own_memory(authz):
    mem = authz.seed()
    user = _hdr("alice")

    assert authz.client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "importance": 9},
        headers=user,
    ).status_code == 200
    edit = authz.last_for("PATCH", "/api/memories/{memory_id}")[-1]
    assert edit.action == "edit"
    assert edit.permission.value == "memory:write:self"
    assert edit.tenant_scoped is False

    assert authz.client.request(
        "DELETE",
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice"},
        headers=user,
    ).status_code == 200
    delete = authz.last_for("DELETE", "/api/memories/{memory_id}")[-1]
    assert delete.permission.value == "memory:delete:self"


def test_a_memory_user_cannot_approve_or_reject_even_its_own_memory(authz):
    """Self-approval defeats the queue that held the memory.

    The `approve` variant declares no self permission, so ownership cannot satisfy
    it — this is the rule the whole contract rests on.
    """
    pending = authz.seed(status=MemStatus.pending, content="claims the launch is in May")
    for target in ("active", "rejected"):
        r = authz.client.patch(
            f"/api/memories/{pending.id}",
            json={"tenant_id": TENANT, "user_id": "alice", "status": target},
            headers=_hdr("alice"),
        )
        assert r.status_code == 403, target
        assert "tenant" in r.json()["detail"]
    assert authz.repo.get_memory(TENANT, "alice", pending.id).status is MemStatus.pending


def test_a_memory_admin_manages_another_users_memory_in_the_same_tenant(authz):
    """Ownership comes from the stored record, so the admin never names the owner —
    they pass their own scope and the loaded record decides."""
    bobs = authz.seed(user="bob", content="bob prefers light mode")
    admin = _hdr("alice", "memory_admin")
    q = f"?tenant_id={TENANT}&user_id=alice"

    assert authz.client.get(f"/api/memories/{bobs.id}{q}", headers=admin).status_code == 200
    read = authz.last_for("GET", "/api/memories/{memory_id}")[-1]
    assert read.permission.value == "memory:read:tenant"
    assert read.tenant_scoped is True, "another user's record must take the tenant branch"

    assert authz.client.patch(
        f"/api/memories/{bobs.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "importance": 3},
        headers=admin,
    ).status_code == 200
    assert authz.repo.get_memory(TENANT, "bob", bobs.id).importance == 3


def test_an_ordinary_user_gets_404_not_403_for_another_users_memory(authz):
    """403 would confirm the record exists, making ids enumerable by status code."""
    bobs = authz.seed(user="bob", content="bob prefers light mode")
    q = f"?tenant_id={TENANT}&user_id=alice"
    user = _hdr("alice")

    assert authz.client.get(f"/api/memories/{bobs.id}{q}", headers=user).status_code == 404
    assert authz.client.get(f"/api/memories/{bobs.id}/audit{q}", headers=user).status_code == 404
    assert (
        authz.client.get(f"/api/memories/{bobs.id}/provenance{q}", headers=user).status_code == 404
    )
    assert authz.client.patch(
        f"/api/memories/{bobs.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "importance": 1},
        headers=user,
    ).status_code == 404


def test_a_memory_admin_still_cannot_read_the_tenant_audit_trail(authz):
    """Managing memory is not reading who did what to it."""
    mem = authz.seed(user="bob")
    q = f"?tenant_id={TENANT}&user_id=alice"
    admin = _hdr("alice", "memory_admin")

    assert authz.client.get(f"/api/memories/{mem.id}{q}", headers=admin).status_code == 200
    assert authz.client.get(f"/api/memories/{mem.id}/audit{q}", headers=admin).status_code == 404


def test_an_auditor_reads_the_trail_but_cannot_mutate_memory(authz):
    mem = authz.seed(user="bob")
    q = f"?tenant_id={TENANT}&user_id=alice"
    auditor = _hdr("alice", "auditor")

    r = authz.client.get(f"/api/memories/{mem.id}/audit{q}", headers=auditor)
    assert r.status_code == 200
    trail = authz.last_for("GET", "/api/memories/{memory_id}/audit")[-1]
    assert trail.permission.value == "audit:read:tenant"

    assert authz.client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "content": "rewritten"},
        headers=auditor,
    ).status_code == 404


def test_a_tenant_admin_cannot_reach_another_tenant(authz):
    """The middleware refuses a mismatched query scope; the record lookup refuses the
    id. Both must hold — neither is allowed to be the only thing standing there."""
    mem = authz.seed()
    admin_elsewhere = _hdr("mallory", "tenant_admin", tenant="evilcorp")

    # Naming acme in the query string: refused before the route.
    r = authz.client.get(
        f"/api/memories/{mem.id}?tenant_id={TENANT}&user_id=alice", headers=admin_elsewhere
    )
    assert r.status_code == 403

    # Naming their own tenant, but acme's memory id: not found in their tenant.
    r = authz.client.get(
        f"/api/memories/{mem.id}?tenant_id=evilcorp&user_id=mallory", headers=admin_elsewhere
    )
    assert r.status_code == 404
    assert authz.repo.get_memory(TENANT, "alice", mem.id) is not None


# ── mixed PATCH: every applicable permission ─────────────────────────────────
_MIXED = {"content": "corrected content", "status": "active"}


def test_a_mixed_patch_requires_both_permissions(authz):
    pending = authz.seed(status=MemStatus.pending, content="original")
    r = authz.client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": TENANT, "user_id": "alice", **_MIXED},
        headers=_hdr("alice", "memory_admin"),
    )
    assert r.status_code == 200, r.text

    actions = {d.action for d in authz.last_for("PATCH", "/api/memories/{memory_id}")}
    assert actions == {"edit", "approve"}, "both actions must be authorized separately"

    stored = authz.repo.get_memory(TENANT, "alice", pending.id)
    assert stored.status is MemStatus.active
    assert stored.content == "corrected content"


def test_approve_permission_without_write_permission_is_refused(monkeypatch):
    """The other direction of the conjunctive rule.

    No shipped role has this shape — every role that can approve can also write — so
    this cannot be driven over HTTP without inventing a role. It is tested at the
    helper anyway, because the rule must hold for whatever roles exist later, and a
    conjunction that has only ever been exercised in one direction is half-tested.
    """
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.auth.decisions import authorize_transition
    from app.auth.principal import Principal
    from app.auth.roles import Permission

    monkeypatch.setattr(
        Principal,
        "permissions",
        property(lambda self: frozenset({Permission.MEMORY_APPROVE_TENANT})),
    )

    class _Route:
        path = "/api/memories/{memory_id}"

    request = SimpleNamespace(
        method="PATCH",
        state=SimpleNamespace(
            principal=Principal(
                tenant_id=TENANT, user_id="alice", provider="trusted_header",
                role_claim_present=True,
            )
        ),
        scope={"route": _Route()},
    )
    spec = ROUTE_AUTHZ[("PATCH", "/api/memories/{memory_id}")]

    # The approval itself is permitted...
    approved = authorize_transition(
        request, spec=spec, validated_action="approve",
        resource_tenant_id=TENANT, resource_user_id="bob",
    )
    assert approved.permission is Permission.MEMORY_APPROVE_TENANT

    # ...but the edit bundled with it is not, so the mixed request cannot proceed.
    with pytest.raises(HTTPException) as exc:
        authorize_transition(
            request, spec=spec, validated_action="edit",
            resource_tenant_id=TENANT, resource_user_id="bob",
        )
    assert exc.value.status_code == 404, "another user's record stays concealed"


def test_a_viewer_cannot_edit_or_approve_a_mixed_patch(authz):
    """The reachable shape of the same rule: a role holding neither permission."""
    pending = authz.seed(status=MemStatus.pending, content="original")
    r = authz.client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": TENANT, "user_id": "alice", **_MIXED},
        headers=_hdr("alice", "memory_viewer"),
    )
    assert r.status_code == 403
    assert authz.repo.get_memory(TENANT, "alice", pending.id).content == "original"


def test_write_permission_without_approve_permission_is_refused(authz):
    """A memory_user may edit their own memory and may not approve it. The mixed
    request must fail as a whole — not apply the edit and skip the approval."""
    pending = authz.seed(status=MemStatus.pending, content="original")
    r = authz.client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": TENANT, "user_id": "alice", **_MIXED},
        headers=_hdr("alice"),
    )
    assert r.status_code == 403
    assert "memory:approve:tenant" in r.json()["detail"]

    stored = authz.repo.get_memory(TENANT, "alice", pending.id)
    assert stored.content == "original", "the edit must not have been applied"
    assert stored.status is MemStatus.pending


def test_a_mixed_patch_records_both_actions_durably(authz):
    """The witness lives for one request. The audit trail is what remains, and it
    said only "approved" about a request that also rewrote the content."""
    pending = authz.seed(status=MemStatus.pending, content="original")
    assert authz.client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": TENANT, "user_id": "alice", **_MIXED},
        headers=_hdr("alice", "memory_admin"),
    ).status_code == 200

    rows = authz.repo.list_audit(TENANT, "alice", memory_id=pending.id, limit=50)
    actions = [r.action for r in rows]
    assert "memory_approved" in actions
    assert any(a.startswith("memory_content") or a == "memory_updated" for a in actions), (
        f"the content edit left no durable record of its own: {actions}"
    )

    for row in rows:
        if row.action == "memory_approved":
            assert row.metadata["requested_actions"] == ["approve", "edit"]
            # `edit` is self-scoped because alice owns the record; `approve` is
            # tenant-scoped because its variant declares no self permission at all.
            assert set(row.metadata["authorized_permissions"]) == {
                "memory:write:self",
                "memory:approve:tenant",
            }
            assert row.metadata["content_updated"] is True
            assert row.metadata["transition"] == "approve"
            break
    else:
        pytest.fail("no memory_approved record")


def test_a_single_action_patch_still_writes_one_record(authz):
    """The mixed case must not turn every patch into two records."""
    mem = authz.seed()
    before = len(authz.repo.list_audit(TENANT, "alice", memory_id=mem.id, limit=50))
    assert authz.client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "importance": 4},
        headers=_hdr("alice"),
    ).status_code == 200
    after = authz.repo.list_audit(TENANT, "alice", memory_id=mem.id, limit=50)
    assert len(after) == before + 1


# ── a refused request leaves nothing behind ──────────────────────────────────
class _Counters:
    """What a request touched, counted across every side-effecting surface.

    A correct status code is not the whole control. If an unauthorized request has
    already opened a loop run, written an audit event, called the policy broker, or
    generated an embedding, then the refusal came too late: the evidence trail now
    contains an action nobody was permitted to take, and the expensive work was done
    on an attacker's schedule.
    """

    def __init__(self, h, monkeypatch):
        self.h = h
        self.policy_calls = 0
        self.embed_calls = 0

        from app.services import policy_broker, update_service

        # Both entry points: `evaluate` on the create path, `evaluate_update` on the
        # edit path. Counting only one would let the other slip through unnoticed.
        for method in ("evaluate", "evaluate_update"):
            original = getattr(policy_broker.PolicyBroker, method)

            def counting(inner_self, *a, _original=original, **kw):
                self.policy_calls += 1
                return _original(inner_self, *a, **kw)

            monkeypatch.setattr(policy_broker.PolicyBroker, method, counting)

        original_update = update_service.apply_content_update

        def counting_update(*a, **kw):
            self.embed_calls += 1
            return original_update(*a, **kw)

        monkeypatch.setattr(update_service, "apply_content_update", counting_update)
        import app.routes.memories as memories_route

        monkeypatch.setattr(memories_route, "apply_content_update", counting_update)

    def snapshot(self) -> dict:
        repo = self.h.repo
        return {
            "loop_runs": len(repo.list_loop_runs(tenant_id=TENANT, user_id="alice", limit=1000))
            + len(repo.list_loop_runs(tenant_id=TENANT, user_id="bob", limit=1000)),
            "loop_events": len(repo.list_loop_events(tenant_id=TENANT, user_id="alice", limit=1000))
            + len(repo.list_loop_events(tenant_id=TENANT, user_id="bob", limit=1000)),
            "audit": len(repo.list_audit(TENANT, None, limit=2000)),
            "policy_calls": self.policy_calls,
            "embed_calls": self.embed_calls,
        }


@pytest.fixture
def counters(authz, monkeypatch):
    return _Counters(authz, monkeypatch)


def _memory_state(repo, memory_id, owner):
    m = repo.get_memory_in_tenant(TENANT, memory_id)
    return (m.content, m.status, m.importance, m.confidence, m.revision)


@pytest.mark.parametrize(
    ("case", "expected_status"),
    [
        ("unauthorized_patch", 403),
        ("unauthorized_delete", 403),
        ("cross_tenant_detail", 404),
        ("self_approval", 403),
        ("mixed_patch_missing_one_permission", 403),
        ("another_users_memory", 404),
    ],
)
def test_a_refused_request_creates_no_side_effects(authz, counters, case, expected_status):
    mine = authz.seed(content="my own note")
    pending = authz.seed(status=MemStatus.pending, content="claims the launch is in May")
    theirs = authz.seed(user="bob", content="bob's note")
    scope = {"tenant_id": TENANT, "user_id": "alice"}
    q = f"?tenant_id={TENANT}&user_id=alice"

    before = counters.snapshot()
    states = {
        m.id: _memory_state(authz.repo, m.id, m.user_id) for m in (mine, pending, theirs)
    }

    if case == "unauthorized_patch":
        r = authz.client.patch(
            f"/api/memories/{mine.id}",
            json={**scope, "content": "rewritten"},
            headers=_hdr("alice", "memory_viewer"),
        )
    elif case == "unauthorized_delete":
        r = authz.client.request(
            "DELETE", f"/api/memories/{mine.id}", json=scope,
            headers=_hdr("alice", "memory_viewer"),
        )
    elif case == "cross_tenant_detail":
        r = authz.client.get(
            f"/api/memories/{mine.id}?tenant_id=evilcorp&user_id=mallory",
            headers=_hdr("mallory", "tenant_admin", tenant="evilcorp"),
        )
    elif case == "self_approval":
        r = authz.client.patch(
            f"/api/memories/{pending.id}", json={**scope, "status": "active"},
            headers=_hdr("alice"),
        )
    elif case == "mixed_patch_missing_one_permission":
        r = authz.client.patch(
            f"/api/memories/{pending.id}",
            json={**scope, "content": "corrected", "status": "active"},
            headers=_hdr("alice"),
        )
    else:  # another_users_memory
        r = authz.client.get(f"/api/memories/{theirs.id}{q}", headers=_hdr("alice"))

    assert r.status_code == expected_status, r.text

    after = counters.snapshot()
    moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not moved, f"{case} left side effects: {moved}"
    for memory_id, state in states.items():
        assert _memory_state(authz.repo, memory_id, None) == state, f"{case} mutated {memory_id}"


def test_the_side_effect_check_would_notice_a_real_request(authz, counters):
    """Proves the counters move at all — otherwise every case above passes vacuously."""
    mem = authz.seed()
    before = counters.snapshot()
    assert authz.client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "content": "a genuine edit"},
        headers=_hdr("alice"),
    ).status_code == 200
    after = counters.snapshot()

    for key in ("loop_runs", "loop_events", "audit", "policy_calls", "embed_calls"):
        assert after[key] > before[key], f"{key} did not move on an authorized edit"


def test_legal_hold_still_overrides_a_permitted_delete(authz):
    """Authorization lets a caller *attempt* a deletion; it never overrides a hold.

    A tenant admin holds every delete permission there is and is still refused, and
    the refusal *is* recorded — unlike an unauthorized attempt, this is a permitted
    action stopped by a preservation control, which is exactly what evidence is for.
    """
    mem = authz.seed()
    admin = _hdr("alice", "tenant_admin")
    assert authz.client.post(
        "/api/retention/legal-hold",
        json={"tenant_id": TENANT, "user_id": "alice", "memory_id": mem.id,
              "on": True, "reason": "litigation"},
        headers=admin,
    ).status_code == 200

    audit_before = len(authz.repo.list_audit(TENANT, "alice", memory_id=mem.id, limit=100))
    r = authz.client.request(
        "DELETE", f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice"}, headers=admin,
    )
    assert r.status_code == 409
    assert authz.repo.get_memory(TENANT, "alice", mem.id).status is MemStatus.active

    rows = authz.repo.list_audit(TENANT, "alice", memory_id=mem.id, limit=100)
    assert len(rows) > audit_before
    assert any(r.action == "memory_legal_hold_delete_blocked" for r in rows)


# ── identity provider parity ─────────────────────────────────────────────────
def _jwt_client(monkeypatch):
    from app import deps
    from app.core import config
    from app.db import factory

    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "jwt")
    monkeypatch.setenv("MEMORYOPS_AUTH_JWT_KEY", FAKE_JWT_SIGNING_KEY)
    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    config.get_settings.cache_clear()
    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app), factory.get_repository()


def _bearer(user: str, roles: list[str] | None = None, tenant: str = TENANT) -> dict:
    import time

    from .test_auth import make_jwt

    claims = {"sub": user, "tenant_id": tenant, "exp": time.time() + 60}
    if roles is not None:
        claims["roles"] = roles
    token = make_jwt(claims, secret=FAKE_JWT_SIGNING_KEY)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["memory_viewer"], 403),  # may read, may not write
        (["memory_user"], 200),  # may edit its own
        (None, 200),  # no claim → DEFAULT_ROLE (memory_user)
        ([], 403),  # claim present but empty → nothing at all
    ],
)
def test_jwt_mode_authorizes_identically_to_trusted_header(monkeypatch, roles, expected):
    """Authorization must depend on the resolved principal, not on how it arrived.

    The two providers reach `Principal` by different routes — a header the proxy
    vouches for, and a signed claim set — and a check that read the header directly,
    or defaulted differently when a claim was absent, would diverge here.
    """
    client, repo = _jwt_client(monkeypatch)
    mem = repo.create_memory(
        StoredMemory(
            tenant_id=TENANT,
            user_id="alice",
            memory_type=MemoryType.preference,
            content="prefers dark mode",
            importance=5,
            confidence=0.8,
            sensitivity=Sensitivity.low,
            status=MemStatus.active,
            source=Source(kind="chat", excerpt="prefers dark mode"),
        )
    )
    r = client.patch(
        f"/api/memories/{mem.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "importance": 7},
        headers=_bearer("alice", roles),
    )
    assert r.status_code == expected, r.text


def test_jwt_self_approval_is_refused_exactly_as_under_trusted_header(monkeypatch):
    client, repo = _jwt_client(monkeypatch)
    pending = repo.create_memory(
        StoredMemory(
            tenant_id=TENANT,
            user_id="alice",
            memory_type=MemoryType.preference,
            content="claims the launch is in May",
            importance=5,
            confidence=0.8,
            sensitivity=Sensitivity.low,
            status=MemStatus.pending,
            source=Source(kind="chat", excerpt="claims the launch is in May"),
        )
    )
    r = client.patch(
        f"/api/memories/{pending.id}",
        json={"tenant_id": TENANT, "user_id": "alice", "status": "active"},
        headers=_bearer("alice", ["memory_user"]),
    )
    assert r.status_code == 403
    assert "memory:approve:tenant" in r.json()["detail"]
    assert repo.get_memory(TENANT, "alice", pending.id).status is MemStatus.pending


def test_a_null_roles_claim_is_refused_at_the_route_with_no_side_effects(monkeypatch):
    """The end-to-end shape of the claim-state fix.

    `{"roles": null}` is an issuer stating this identity has no roles. Read as an
    omitted claim it took the compatibility fallback to `memory_user` — which carries
    `memory:write:self`, so the chat write path ran for a credential meant to carry
    nothing. The refusal must also land before any of it: no loop run, no audit event,
    no policy-broker call, no memory.
    """
    import time

    from app.services import policy_broker

    from .test_auth import make_jwt

    client, repo = _jwt_client(monkeypatch)

    calls = {"policy": 0}
    original = policy_broker.PolicyBroker.evaluate

    def counting(inner_self, *a, **kw):
        calls["policy"] += 1
        return original(inner_self, *a, **kw)

    monkeypatch.setattr(policy_broker.PolicyBroker, "evaluate", counting)

    def _token(claims: dict) -> dict:
        payload = {"sub": "alice", "tenant_id": TENANT, "exp": time.time() + 60, **claims}
        return {"Authorization": f"Bearer {make_jwt(payload, secret=FAKE_JWT_SIGNING_KEY)}"}

    body = {"tenant_id": TENANT, "user_id": "alice", "message": "remember I prefer dark mode"}

    runs_before = len(repo.list_loop_runs(tenant_id=TENANT, user_id="alice", limit=1000))
    audit_before = len(repo.list_audit(TENANT, "alice", limit=1000))

    refused = client.post("/api/chat", json=body, headers=_token({"roles": None}))
    assert refused.status_code == 403
    assert "memory:write:self" in refused.json()["detail"]

    assert len(repo.list_loop_runs(tenant_id=TENANT, user_id="alice", limit=1000)) == runs_before
    assert len(repo.list_audit(TENANT, "alice", limit=1000)) == audit_before
    assert calls["policy"] == 0
    assert repo.list_memories(TENANT, "alice") == []

    # The same request with the claim genuinely omitted still works, so the refusal
    # is the null claim being honoured — not chat being broken for everyone.
    allowed = client.post("/api/chat", json=body, headers=_token({}))
    assert allowed.status_code == 200
    assert calls["policy"] > 0
