"""Authorization on the governance and evidence reads.

The separation this file exists to hold: **managing memory is not reading the record
of who managed it.** `memory_admin` can edit and delete anyone's memory in the tenant
and still cannot read the traces, evidence, or eval results that would show them doing
it. That is the whole point of having an auditor role, and it is exactly the property
the web app's old role ladder did not have — where `memory_admin` sat *above*
`auditor` and inherited everything.

Retention is the deliberate exception: it is lifecycle management, so `memory_admin`
holds `retention:read` too.
"""

from __future__ import annotations

import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.authz_spec import ROUTE_AUTHZ, Status
from app.auth.witness import witness_for
from app.db.entities import StoredMemory
from app.schemas.memory import MemoryType, Sensitivity, Source
from app.schemas.memory import Status as MemStatus

from ._authz_domains import enforced_in, is_governance_read
from ._secret_fixtures import FAKE_JWT_SIGNING_KEY

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
    monkeypatch.setenv("MEMORYOPS_TRACING_ENABLED", "true")
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

        def seed(self, *, user="alice", tenant=TENANT, content="prefers dark mode"):
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


def _paths(h, memory_id: str, trace_id: str) -> dict[tuple[str, str], str]:
    """Every enforced governance read, mapped to a concrete URL."""
    q = f"?tenant_id={TENANT}&user_id=alice"
    return {
        ("GET", "/api/evidence/audit/verify"): f"/api/evidence/audit/verify{q}",
        ("GET", "/api/evidence/policy"): f"/api/evidence/policy{q}",
        ("GET", "/api/evidence/response/{trace_id}"): f"/api/evidence/response/{trace_id}{q}",
        ("GET", "/api/evidence/deletion/{memory_id}"): f"/api/evidence/deletion/{memory_id}{q}",
        ("GET", "/api/evidence/lifecycle/{memory_id}"): f"/api/evidence/lifecycle/{memory_id}{q}",
        ("GET", "/api/retention/policies"): f"/api/retention/policies{q}",
        ("GET", "/api/retention/decisions"): f"/api/retention/decisions{q}",
        ("GET", "/api/retention/memory/{memory_id}"): f"/api/retention/memory/{memory_id}{q}",
        ("GET", "/api/loops"): f"/api/loops{q}",
        ("GET", "/api/loops/{loop_id}"): f"/api/loops/memory.write{q}",
        ("GET", "/api/loops/runs"): f"/api/loops/runs{q}",
        ("GET", "/api/loops/events"): f"/api/loops/events{q}",
        ("GET", "/api/loops/trace/{trace_id}"): f"/api/loops/trace/{trace_id}{q}",
    }


# ── the runtime witness gate ─────────────────────────────────────────────────
def test_every_enforced_governance_read_records_a_decision(gov):
    """Drives each route through the real app and reads its witness back.

    Not two lists agreeing — a handler that stops calling the helper still returns
    200 for this (fully authorized) caller, and only the missing witness reveals it.
    """
    mem = gov.seed()
    everything = _hdr("alice", "tenant_admin")
    trace = "trace-gov"
    gov.client.post(
        "/api/chat",
        json={"tenant_id": TENANT, "user_id": "alice", "message": "hello", "trace_id": trace},
        headers=everything,
    )
    urls = _paths(gov, mem.id, trace)

    expected = enforced_in(ROUTE_AUTHZ, Status.ENFORCED, is_governance_read)
    assert set(urls) == expected, (
        "the gate does not drive every enforced governance route: "
        f"{sorted(set(urls) ^ expected)}"
    )

    gov.clear()
    for route, url in urls.items():
        r = gov.client.get(url, headers=everything)
        assert r.status_code == 200, f"{route}: {r.status_code} {r.text[:200]}"

    witnessed = {d.route for d in gov.decisions}
    missing = expected - witnessed
    assert not missing, f"enforced but no authorization decision recorded: {sorted(missing)}"


def test_the_governance_witness_gate_is_not_vacuous(gov, monkeypatch):
    """Neuter one representative handler's check; the request still succeeds and the
    gate must notice the absent witness."""
    import app.routes.loops as loops_route

    monkeypatch.setattr(loops_route, "_tenant_of", lambda request, requested: requested)
    gov.clear()

    r = gov.client.get(
        f"/api/loops/runs?tenant_id={TENANT}&user_id=alice", headers=_hdr("alice", "auditor")
    )
    assert r.status_code == 200, "the neutered handler still answers normally"
    assert not gov.last_for("GET", "/api/loops/runs"), (
        "no decision recorded — the gate cannot detect a handler that stopped checking"
    )


# ── role separation ──────────────────────────────────────────────────────────
_AUDITOR_ONLY = pytest.mark.parametrize(
    "path_for",
    [
        pytest.param(lambda m, t: "/api/evidence/policy", id="evidence-policy"),
        pytest.param(lambda m, t: "/api/evidence/audit/verify", id="evidence-verify"),
        pytest.param(lambda m, t: f"/api/evidence/deletion/{m}", id="evidence-deletion"),
        pytest.param(lambda m, t: f"/api/evidence/lifecycle/{m}", id="evidence-lifecycle"),
        pytest.param(lambda m, t: f"/api/evidence/response/{t}", id="evidence-bundle"),
        pytest.param(lambda m, t: "/api/loops/runs", id="loop-runs"),
        pytest.param(lambda m, t: "/api/loops/events", id="loop-events"),
        pytest.param(lambda m, t: f"/api/loops/trace/{t}", id="loop-trace"),
    ],
)


@_AUDITOR_ONLY
def test_an_auditor_may_read_governance_evidence(gov, path_for):
    mem = gov.seed()
    q = f"?tenant_id={TENANT}&user_id=alice"
    r = gov.client.get(f"{path_for(mem.id, 'trace-x')}{q}", headers=_hdr("alice", "auditor"))
    assert r.status_code == 200, r.text


@_AUDITOR_ONLY
def test_a_memory_admin_may_not_read_governance_evidence(gov, path_for):
    """The load-bearing separation. `memory_admin` outranks `auditor` in the web
    persona ladder and must not inherit its reads at the API."""
    mem = gov.seed()
    q = f"?tenant_id={TENANT}&user_id=alice"
    r = gov.client.get(f"{path_for(mem.id, 'trace-x')}{q}", headers=_hdr("alice", "memory_admin"))
    assert r.status_code == 403, r.text


@_AUDITOR_ONLY
def test_an_ordinary_user_may_not_read_governance_evidence(gov, path_for):
    mem = gov.seed()
    q = f"?tenant_id={TENANT}&user_id=alice"
    for roles in (None, "memory_viewer", "service_worker"):
        r = gov.client.get(f"{path_for(mem.id, 'trace-x')}{q}", headers=_hdr("alice", roles))
        assert r.status_code == 403, f"{roles}: {r.text}"


@pytest.mark.parametrize(
    "path_for",
    [
        pytest.param(lambda m: "/api/retention/policies", id="policies"),
        pytest.param(lambda m: "/api/retention/decisions", id="decisions"),
        pytest.param(lambda m: f"/api/retention/memory/{m}", id="memory"),
    ],
)
def test_retention_reads_are_open_to_both_admin_and_auditor(gov, path_for):
    """Deliberately different: retention describes what the system will forget, which
    is lifecycle management — a memory admin's job — not the record of who acted."""
    mem = gov.seed()
    q = f"?tenant_id={TENANT}&user_id=alice"
    for role in ("auditor", "memory_admin", "tenant_admin"):
        r = gov.client.get(f"{path_for(mem.id)}{q}", headers=_hdr("alice", role))
        assert r.status_code == 200, f"{role}: {r.text}"
    for role in (None, "memory_viewer"):
        r = gov.client.get(f"{path_for(mem.id)}{q}", headers=_hdr("alice", role))
        assert r.status_code == 403, f"{role}: {r.text}"


# ── the authenticated-only loop definitions ──────────────────────────────────
def test_any_authenticated_caller_reads_the_static_loop_definitions(gov):
    """Classified `authenticated`, and enforced as exactly that — no borrowed
    permission, because the route needs none and claiming one would be a lie in the
    matrix."""
    q = f"?tenant_id={TENANT}&user_id=alice"
    for roles in (None, "memory_viewer", "memory_user", "auditor", "service_worker"):
        for url in (f"/api/loops{q}", f"/api/loops/memory.write{q}"):
            r = gov.client.get(url, headers=_hdr("alice", roles))
            assert r.status_code == 200, f"{roles} {url}: {r.text}"

    decision = gov.last_for("GET", "/api/loops")[-1]
    assert decision.helper == "require_authenticated"
    assert decision.permission is None
    assert decision.tenant_scoped is False


def test_an_ordinary_user_cannot_read_loop_runs_or_events(gov):
    """Definitions are documentation; runs and events are this tenant's activity."""
    q = f"?tenant_id={TENANT}&user_id=alice"
    for url in (f"/api/loops/runs{q}", f"/api/loops/events{q}"):
        assert gov.client.get(url, headers=_hdr("alice")).status_code == 403


def test_the_loop_definitions_still_need_a_credential(gov):
    assert gov.client.get(f"/api/loops?tenant_id={TENANT}&user_id=alice").status_code == 401


# ── cross-tenant ─────────────────────────────────────────────────────────────
def test_an_authorized_caller_cannot_reach_another_tenants_evidence(gov):
    """Permission is not scope. A tenant admin has every capability and still cannot
    see another tenant's records."""
    theirs = gov.seed(tenant="evilcorp", user="mallory", content="their private note")
    admin = _hdr("alice", "tenant_admin")
    q = f"?tenant_id={TENANT}&user_id=alice"

    r = gov.client.get(f"/api/retention/memory/{theirs.id}{q}", headers=admin)
    assert r.status_code == 404
    assert "their private note" not in r.text

    for path in (
        f"/api/evidence/deletion/{theirs.id}",
        f"/api/evidence/lifecycle/{theirs.id}",
    ):
        r = gov.client.get(f"{path}{q}", headers=admin)
        assert r.status_code == 200
        assert r.json()["found"] is False, "another tenant's record must not resolve"
        assert "their private note" not in r.text

    # Naming the other tenant outright is refused before the route.
    assert gov.client.get(
        "/api/loops/runs?tenant_id=evilcorp&user_id=mallory", headers=admin
    ).status_code == 403


def test_only_the_authenticated_tenant_reaches_the_repository(gov, monkeypatch):
    """The query must be built from the principal, not from the request."""
    seen: list = []
    repo = gov.repo
    original = repo.list_loop_runs

    def spy(*a, **kw):
        seen.append(kw.get("tenant_id"))
        return original(*a, **kw)

    monkeypatch.setattr(repo, "list_loop_runs", spy)
    r = gov.client.get(
        f"/api/loops/runs?tenant_id={TENANT}&user_id=alice", headers=_hdr("alice", "auditor")
    )
    assert r.status_code == 200
    assert seen == [TENANT]


# ── a refused read leaves nothing behind ─────────────────────────────────────
class _Counters:
    """Every surface a refused *read* must not touch.

    Reads are the easy case to get wrong in the opposite direction: they look
    side-effect-free, so it is tempting to authorize late. But these routes write
    audit events, open loop runs, and — for `/api/evals/latest` — can regenerate an
    eval run, which is real compute an unauthorized caller must never be able to
    trigger.
    """

    def __init__(self, h, monkeypatch):
        self.h = h

    def snapshot(self) -> dict:
        repo = self.h.repo
        return {
            "audit": len(repo.list_audit(TENANT, limit=2000)),
            "loop_runs": len(repo.list_loop_runs(tenant_id=TENANT, limit=1000)),
            "loop_events": len(repo.list_loop_events(tenant_id=TENANT, limit=1000)),
            "memories": len(repo.list_memories(TENANT, "alice")),
        }


@pytest.fixture
def counters(gov, monkeypatch):
    return _Counters(gov, monkeypatch)


@pytest.mark.parametrize(
    "path_for",
    [
        pytest.param(lambda m, t: "/api/evidence/policy", id="evidence-policy"),
        pytest.param(lambda m, t: f"/api/evidence/deletion/{m}", id="evidence-deletion"),
        pytest.param(lambda m, t: "/api/loops/runs", id="loop-runs"),
        pytest.param(lambda m, t: f"/api/loops/trace/{t}", id="loop-trace"),
        pytest.param(lambda m, t: "/api/retention/decisions", id="retention-decisions"),
    ],
)
def test_a_refused_read_creates_no_side_effects(gov, counters, path_for):
    mem = gov.seed()
    q = f"?tenant_id={TENANT}&user_id=alice"
    before = counters.snapshot()

    r = gov.client.get(f"{path_for(mem.id, 'trace-x')}{q}", headers=_hdr("alice", "memory_viewer"))
    assert r.status_code == 403, r.text

    after = counters.snapshot()
    moved = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
    assert not moved, f"refused read left side effects: {moved}"


def test_authorized_reads_do_move_the_counters(gov, counters):
    """Positive control for the whole class above.

    A zero-side-effect assertion passes trivially if the instrumentation is broken,
    so at least one authorized read must be shown to write evidence.
    """
    gov.seed()
    before = counters.snapshot()

    # A memory detail read is audited; chat opens loop runs and stores memory.
    assert gov.client.post(
        "/api/chat",
        json={"tenant_id": TENANT, "user_id": "alice", "message": "Remember I prefer tea."},
        headers=_hdr("alice", "tenant_admin"),
    ).status_code == 200
    after = counters.snapshot()

    for key in ("audit", "loop_runs", "loop_events"):
        assert after[key] > before[key], f"{key} did not move on an authorized request"


# ── provider parity + claim states ───────────────────────────────────────────
@pytest.fixture
def jwt_client(monkeypatch):
    """A JWT-mode client that also clears the settings cache on the way *out*.

    Without the teardown, `get_settings` stayed cached as `auth_mode="jwt"` after the
    monkeypatched env var was restored, so the next test in the file ran against a
    configuration that no longer existed.
    """
    from app import deps
    from app.core import config
    from app.db import factory

    def _clear():
        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()

    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "jwt")
    monkeypatch.setenv("MEMORYOPS_AUTH_JWT_KEY", FAKE_JWT_SIGNING_KEY)
    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    _clear()
    from fastapi.testclient import TestClient

    from app.main import app

    yield TestClient(app)
    _clear()


def _bearer(roles, user: str = "alice", tenant: str = TENANT) -> dict:
    import time

    from .test_auth import make_jwt

    claims = {"sub": user, "tenant_id": tenant, "exp": time.time() + 60}
    if roles is not _OMITTED:
        claims["roles"] = roles
    return {"Authorization": f"Bearer {make_jwt(claims, secret=FAKE_JWT_SIGNING_KEY)}"}


_OMITTED = object()


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        (["auditor"], 200),
        (["memory_admin"], 403),
        (["memory_viewer"], 403),
        (_OMITTED, 403),  # default role has no governance reads
        (None, 403),  # explicit null -> nothing
        ([], 403),
        (["not_a_role"], 403),
    ],
)
def test_jwt_governance_reads_match_trusted_header(jwt_client, roles, expected):
    """Authorization depends on the resolved principal, not on how it arrived — and
    every role-claim state resolves the same way it does for memory routes."""
    r = jwt_client.get(
        f"/api/evidence/policy?tenant_id={TENANT}&user_id=alice", headers=_bearer(roles)
    )
    assert r.status_code == expected, r.text


def test_the_static_loop_definitions_need_only_a_valid_credential_under_jwt(jwt_client):
    """`authenticated` means authenticated under either provider — including a
    credential the issuer stripped of every role."""
    q = f"?tenant_id={TENANT}&user_id=alice"
    for roles in (["auditor"], [], None, ["not_a_role"]):
        assert jwt_client.get(f"/api/loops{q}", headers=_bearer(roles)).status_code == 200
    assert jwt_client.get(f"/api/loops{q}").status_code == 401


def test_governance_reads_are_unchanged_with_auth_disabled(api_client):
    """The development default: no principal, so nothing to authorize, and every
    surface still answers."""
    client, _repo = api_client
    q = "?tenant_id=t1&user_id=u1"
    for url in (
        f"/api/evidence/policy{q}",
        f"/api/evidence/audit/verify{q}",
        f"/api/retention/policies{q}",
        f"/api/retention/decisions{q}",
        f"/api/loops{q}",
        f"/api/loops/runs{q}",
        f"/api/loops/events{q}",
    ):
        assert client.get(url).status_code == 200, url
