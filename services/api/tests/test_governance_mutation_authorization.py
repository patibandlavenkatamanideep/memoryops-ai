"""Authorization on the four governance mutations.

The defect this fixes
---------------------
`_load()` called `enforce_scope(request, req.tenant_id, req.user_id)` and then looked
the memory up with `repo.get_memory(req.tenant_id, req.user_id, ...)`. Both halves
trusted the request's `user_id`, so a `memory_admin` could not manage another user's
record by either route:

    names the real owner  -> 403 (scope validation rejects a user that is not you)
    names themselves      -> 404 (the lookup cannot find someone else's memory)

The fix is the same rule the memory routes already follow: the request's `user_id` is
a hint about where to look; the **stored** owner is authoritative for the mutation and
for the audit record.

Which raises a second problem. Once an admin can act on someone else's governance
state, `audit.user_id = "bob"` no longer says whether Bob acted or was acted upon, so
actor and target are now recorded separately.
"""

from __future__ import annotations

import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.authz_spec import ROUTE_AUTHZ, Status
from app.auth.witness import witness_for
from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source
from app.schemas.memory import Status as MemStatus

from ._authz_domains import enforced_in, is_governance_mutation

TENANT = "acme"


def _hdr(user: str, roles: str | None = None, tenant: str = TENANT) -> dict:
    h = {"X-MemoryOps-Tenant": tenant, "X-MemoryOps-User": user}
    if roles:
        h["X-MemoryOps-Roles"] = roles
    return h


@pytest.fixture
def gov(monkeypatch):
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

    app.middleware_stack = None
    app.add_middleware(BaseHTTPMiddleware, dispatch=_capture)

    client = TestClient(app)
    repo = factory.get_repository()

    class Harness:
        def __init__(self):
            self.client = client
            self.repo = repo
            self.decisions = recorded

        def seed(self, *, user="bob", tenant=TENANT, content="a governed note"):
            return repo.create_memory(
                StoredMemory(
                    tenant_id=tenant,
                    user_id=user,
                    memory_type=MemoryType.preference,
                    content=content,
                    importance=5,
                    confidence=0.8,
                    sensitivity=Sensitivity.low,
                    status=MemStatus.active,
                    source=Source(kind="chat", excerpt=content),
                )
            )

        def audit_for(self, memory_id):
            return repo.list_audit(TENANT, None, memory_id=memory_id, limit=50)

        def last_for(self, method, path):
            return [d for d in recorded if d.route == (method, path)]

        def clear(self):
            recorded.clear()

    yield Harness()
    app.user_middleware = [
        m for m in app.user_middleware if m.kwargs.get("dispatch") is not _capture
    ]
    app.middleware_stack = None
    _clear()


#: (route path, body beyond scope, permission it must require)
_MUTATIONS = [
    pytest.param("/api/retention/legal-hold", {"on": True, "reason": "litigation"},
                 "retention:manage", id="legal-hold"),
    pytest.param("/api/retention/pin", {"on": True}, "retention:manage", id="pin"),
    pytest.param("/api/retention/protect", {"on": True}, "retention:manage", id="protect"),
    pytest.param("/api/retention/consent", {"status": "withdrawn"}, "consent:manage",
                 id="consent"),
]


def _body(memory_id: str, extra: dict, user: str = "alice") -> dict:
    return {"tenant_id": TENANT, "user_id": user, "memory_id": memory_id, **extra}


# ── the reproduction ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_an_admin_governs_another_users_memory(gov, path, extra, permission):
    """Neither addressing mode worked before: naming the owner was refused by scope
    validation, and naming yourself found nothing."""
    mem = gov.seed(user="bob")
    r = gov.client.post(
        path, json=_body(mem.id, extra), headers=_hdr("alice", "memory_admin")
    )
    assert r.status_code == 200, r.text

    decision = gov.last_for("POST", path)[-1]
    assert decision.permission.value == permission


@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_the_stored_owner_wins_over_whatever_the_request_claims(gov, path, extra, permission):
    """A caller-supplied `user_id` must not steer the mutation or the audit target."""
    mem = gov.seed(user="bob")
    r = gov.client.post(
        path,
        json=_body(mem.id, extra, user="alice"),  # not the owner
        headers=_hdr("alice", "memory_admin"),
    )
    assert r.status_code == 200, r.text

    stored = gov.repo.get_memory_in_tenant(TENANT, mem.id)
    assert stored.user_id == "bob"
    row = gov.audit_for(mem.id)[0]
    assert row.user_id == "bob", "the audit target is the stored owner, not the request"


@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_actor_and_target_are_recorded_separately(gov, path, extra, permission):
    """`user_id: bob` alone cannot say whether Bob acted or was acted upon."""
    mem = gov.seed(user="bob")
    assert gov.client.post(
        path, json=_body(mem.id, extra), headers=_hdr("alice", "memory_admin")
    ).status_code == 200

    row = gov.audit_for(mem.id)[0]
    assert row.user_id == "bob"
    assert row.metadata["actor_user_id"] == "alice"
    assert row.metadata["target_user_id"] == "bob"
    assert row.metadata["actor_type"] == "human"
    assert row.metadata["authorized_permission"] == permission
    assert row.metadata["acted_on_behalf_of_another_user"] is True

    # Content-free: no credential, no claims, no memory text.
    blob = str(row.metadata)
    assert "a governed note" not in blob
    assert "X-MemoryOps" not in blob and "Bearer" not in blob


def test_self_service_is_not_labelled_as_acting_for_someone_else(gov):
    mem = gov.seed(user="alice")
    assert gov.client.post(
        "/api/retention/pin",
        json=_body(mem.id, {"on": True}),
        headers=_hdr("alice", "memory_admin"),
    ).status_code == 200
    row = gov.audit_for(mem.id)[0]
    assert row.metadata["acted_on_behalf_of_another_user"] is False


# ── role separation ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
@pytest.mark.parametrize(
    "role", ["auditor", "memory_user", "memory_viewer", "service_worker", None]
)
def test_roles_without_the_permission_are_refused(gov, path, extra, permission, role):
    """An auditor reads governance evidence and must not be able to change it."""
    mem = gov.seed(user="alice")
    r = gov.client.post(path, json=_body(mem.id, extra), headers=_hdr("alice", role))
    assert r.status_code == 403, f"{role}: {r.text}"
    assert permission in r.json()["detail"]


@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_a_tenant_admin_governs_its_own_tenant(gov, path, extra, permission):
    mem = gov.seed(user="bob")
    assert gov.client.post(
        path, json=_body(mem.id, extra), headers=_hdr("alice", "tenant_admin")
    ).status_code == 200


@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_no_role_reaches_another_tenant(gov, path, extra, permission):
    """Permission is not scope."""
    theirs = gov.seed(tenant="evilcorp", user="mallory", content="their private note")
    admin = _hdr("alice", "tenant_admin")

    # Their memory id, our tenant: not found in the authenticated tenant.
    r = gov.client.post(path, json=_body(theirs.id, extra), headers=admin)
    assert r.status_code == 404
    assert "their private note" not in r.text

    # Naming their tenant outright: refused before the record is touched.
    body = {**_body(theirs.id, extra), "tenant_id": "evilcorp", "user_id": "mallory"}
    assert gov.client.post(path, json=body, headers=admin).status_code == 403

    untouched = gov.repo.get_memory_in_tenant("evilcorp", theirs.id)
    from app.db import governance as gov_state

    assert gov_state.public_governance(untouched) == gov_state.public_governance(theirs)


# ── a refused mutation does nothing at all ───────────────────────────────────
class _Counters:
    def __init__(self, h, monkeypatch):
        self.h = h
        self.lookups = 0
        self.transactions = 0
        repo = h.repo

        for name in ("get_memory", "get_memory_in_tenant"):
            original = getattr(repo, name)

            def counting(*a, _o=original, **kw):
                self.lookups += 1
                return _o(*a, **kw)

            monkeypatch.setattr(repo, name, counting)

        original_tx = repo.transaction

        def counting_tx(*a, **kw):
            self.transactions += 1
            return original_tx(*a, **kw)

        monkeypatch.setattr(repo, "transaction", counting_tx)

    def snapshot(self) -> dict:
        repo = self.h.repo
        return {
            "lookups": self.lookups,
            "transactions": self.transactions,
            "audit": len(repo.list_audit(TENANT, limit=2000)),
            "loop_runs": len(repo.list_loop_runs(tenant_id=TENANT, limit=1000)),
            "loop_events": len(repo.list_loop_events(tenant_id=TENANT, limit=1000)),
        }


@pytest.fixture
def counters(gov, monkeypatch):
    return _Counters(gov, monkeypatch)


@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_a_refused_mutation_reaches_nothing(gov, counters, path, extra, permission):
    """Authorization runs before the repository lookup, so a refused caller cannot
    even probe which memory ids exist, let alone open a transaction."""
    from app.db import governance as gov_state

    mem = gov.seed(user="bob")
    before_state = gov_state.public_governance(gov.repo.get_memory_in_tenant(TENANT, mem.id))
    before = counters.snapshot()

    r = gov.client.post(path, json=_body(mem.id, extra), headers=_hdr("alice", "auditor"))
    assert r.status_code == 403

    after = counters.snapshot()
    moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not moved, f"refused mutation left side effects: {moved}"

    stored = gov.repo.get_memory_in_tenant(TENANT, mem.id)
    assert gov_state.public_governance(stored) == before_state


def test_the_side_effect_counters_move_on_an_authorized_mutation(gov, counters):
    """Positive control — the assertions above are worthless if nothing is wired."""
    mem = gov.seed(user="bob")
    before = counters.snapshot()
    assert gov.client.post(
        "/api/retention/pin",
        json=_body(mem.id, {"on": True}),
        headers=_hdr("alice", "memory_admin"),
    ).status_code == 200
    after = counters.snapshot()
    for key in ("lookups", "transactions", "audit"):
        assert after[key] > before[key], f"{key} did not move on an authorized mutation"


def test_an_unauthorized_request_for_a_nonexistent_memory_is_still_403(gov):
    """403 before 404: the refusal must not double as an existence oracle."""
    r = gov.client.post(
        "/api/retention/pin",
        json=_body("no-such-memory", {"on": True}),
        headers=_hdr("alice", "auditor"),
    )
    assert r.status_code == 403


def test_consent_validation_does_not_leak_record_existence(gov):
    """The status vocabulary check runs before authorization, which is safe only
    because it inspects nothing but the request body. Pinned so it stays that way."""
    r = gov.client.post(
        "/api/retention/consent",
        json=_body("no-such-memory", {"status": "not-a-status"}),
        headers=_hdr("alice", "auditor"),
    )
    assert r.status_code == 422
    assert "unknown consent status" in r.json()["detail"]

    # A *valid* status with no permission is refused without touching the record.
    r = gov.client.post(
        "/api/retention/consent",
        json=_body("no-such-memory", {"status": "withdrawn"}),
        headers=_hdr("alice", "auditor"),
    )
    assert r.status_code == 403


# ── atomicity ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("path", "extra", "permission"), _MUTATIONS)
def test_the_mutation_rolls_back_when_its_audit_fails(gov, monkeypatch, path, extra, permission):
    """Invariant #7 across the newly authorized paths: governance state and its
    evidence commit together or not at all."""
    from app.db import governance as gov_state

    mem = gov.seed(user="bob")
    before = gov_state.public_governance(gov.repo.get_memory_in_tenant(TENANT, mem.id))

    from app import deps

    service = deps.audit_service()
    monkeypatch.setattr(
        service, "record", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("audit down"))
    )

    with pytest.raises(RuntimeError):
        gov.client.post(path, json=_body(mem.id, extra), headers=_hdr("alice", "memory_admin"))

    stored = gov.repo.get_memory_in_tenant(TENANT, mem.id)
    assert gov_state.public_governance(stored) == before, (
        "the governance mutation survived a failed audit"
    )


# ── the runtime witness gate ─────────────────────────────────────────────────
def test_every_enforced_mutation_records_a_decision(gov):
    mem = gov.seed(user="bob")
    gov.clear()
    driven = set()
    for path, extra, _perm in [(p.values[0], p.values[1], p.values[2]) for p in _MUTATIONS]:
        r = gov.client.post(
            path, json=_body(mem.id, extra), headers=_hdr("alice", "tenant_admin")
        )
        assert r.status_code == 200, f"{path}: {r.text}"
        driven.add(("POST", path))

    expected = enforced_in(ROUTE_AUTHZ, Status.ENFORCED, is_governance_mutation)
    assert driven == expected, f"gate does not drive every enforced mutation: {driven ^ expected}"

    witnessed = {d.route for d in gov.decisions}
    assert not expected - witnessed, f"no decision recorded for {sorted(expected - witnessed)}"


def test_the_mutation_witness_gate_is_not_vacuous(gov, monkeypatch):
    """Remove the permission check; the request still succeeds and the gate must
    notice the missing witness."""
    import app.routes.retention as retention_route

    monkeypatch.setattr(retention_route, "require_permission", lambda request, permission: None)
    mem = gov.seed(user="alice")
    gov.clear()

    r = gov.client.post(
        "/api/retention/pin",
        json=_body(mem.id, {"on": True}),
        headers=_hdr("alice", "auditor"),
    )
    assert r.status_code == 200, "the unchecked handler still answers normally"
    assert not gov.last_for("POST", "/api/retention/pin"), (
        "no decision recorded — the gate cannot detect a handler that stopped checking"
    )


def test_governance_mutations_are_unchanged_with_auth_disabled(api_client):
    """Development default: no principal, so the request scope stands."""
    from app.db.entities import StoredMemory

    client, repo = api_client
    mem = repo.create_memory(
        StoredMemory(
            tenant_id="t1",
            user_id="u1",
            memory_type=MemoryType.preference,
            content="a note",
            importance=5,
            confidence=0.8,
            sensitivity=Sensitivity.low,
            status=MemStatus.active,
            source=Source(kind="chat", excerpt="a note"),
        )
    )
    body = {"tenant_id": "t1", "user_id": "u1", "memory_id": mem.id}
    for path, extra in (
        ("/api/retention/legal-hold", {"on": True, "reason": "x"}),
        ("/api/retention/pin", {"on": True}),
        ("/api/retention/protect", {"on": True}),
        ("/api/retention/consent", {"status": "granted"}),
    ):
        assert client.post(path, json={**body, **extra}).status_code == 200, path
