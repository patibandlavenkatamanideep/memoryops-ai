"""The deployment boundary: `ops:*` permissions and the `platform_operator` role.

The distinction this file defends
---------------------------------
"Administrator of tenant A" and "operator of this deployment" are different
authorities. Three surfaces describe the *installation* rather than any tenant:

* `/api/traces` — a process-wide span buffer with no tenant dimension
* `/api/evals/{latest,run}` — a harness over its own fixtures, and a process-wide
  result store
* `/api/admin/workers/health` — the worker fleet

Before this, `tenant_admin` held `frozenset(set(Permission))`, so a tenant
administrator could read deployment telemetry and spend platform compute — replacing
the evaluation result every *other* tenant reads. That is not tenant administration.
"""

from __future__ import annotations

import pytest
from starlette.middleware.base import BaseHTTPMiddleware

import app.routes.evals as evals_route
from app.auth.authz_spec import ROUTE_AUTHZ, Status
from app.auth.witness import witness_for

from ._authz_domains import enforced_in, is_operational_domain

TENANT = "acme"


def _hdr(user: str = "alice", roles: str | None = None, tenant: str = TENANT) -> dict:
    h = {"X-MemoryOps-Tenant": tenant, "X-MemoryOps-User": user}
    if roles:
        h["X-MemoryOps-Roles"] = roles
    return h


@pytest.fixture
def ops(monkeypatch):
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
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "true")
    _clear()
    evals_route.reset_cache()

    harness = {"runs": 0}
    original = evals_route.run_evals

    class _Result:
        def to_dict(self):
            harness["runs"] += 1
            return {"total": 2, "passed": 2, "failed": 0, "pass_rate": 1.0, "run": harness["runs"]}

    monkeypatch.setattr(evals_route, "run_evals", lambda *a, **kw: _Result())

    from fastapi.testclient import TestClient

    from app.main import app

    recorded: list = []

    async def _capture(request, call_next):
        response = await call_next(request)
        recorded.extend(witness_for(request).decisions)
        return response

    app.middleware_stack = None
    app.add_middleware(BaseHTTPMiddleware, dispatch=_capture)

    class Harness:
        def __init__(self):
            self.client = TestClient(app)
            self.decisions = recorded
            self.harness = harness
            self.real_run_evals = original

        def last_for(self, method, path):
            return [d for d in recorded if d.route == (method, path)]

        def clear(self):
            recorded.clear()

    yield Harness()
    app.user_middleware = [
        m for m in app.user_middleware if m.kwargs.get("dispatch") is not _capture
    ]
    app.middleware_stack = None
    evals_route.reset_cache()
    _clear()


_OPERATOR = "platform_operator"
#: Every tenant role, however senior. None may reach a deployment surface.
_TENANT_ROLES = ["tenant_admin", "memory_admin", "auditor", "memory_user", "memory_viewer",
                 "service_worker", None]


# ── the escalation this prevents ─────────────────────────────────────────────
@pytest.mark.parametrize("role", _TENANT_ROLES)
def test_no_tenant_role_reads_deployment_traces(ops, role):
    r = ops.client.get("/api/traces", headers=_hdr(roles=role))
    assert r.status_code == 403, f"{role}: {r.text}"
    assert "ops:traces:read" in r.json()["detail"]


@pytest.mark.parametrize("role", _TENANT_ROLES)
def test_no_tenant_role_reads_the_deployment_eval_result(ops, role):
    r = ops.client.get("/api/evals/latest", headers=_hdr(roles=role))
    assert r.status_code == 403, f"{role}: {r.text}"
    assert "ops:evals:read" in r.json()["detail"]


@pytest.mark.parametrize("role", _TENANT_ROLES)
def test_no_tenant_role_can_spend_platform_compute(ops, role):
    """The sharpest case: a tenant admin running the harness would spend the
    deployment's compute *and* replace the result every other tenant reads."""
    r = ops.client.post("/api/evals/run", headers=_hdr(roles=role))
    assert r.status_code == 403, f"{role}: {r.text}"
    assert "ops:evals:run" in r.json()["detail"]
    assert ops.harness["runs"] == 0, "a refused run must never reach the harness"


# ── the operator can ─────────────────────────────────────────────────────────
def test_the_operator_reads_traces(ops):
    r = ops.client.get("/api/traces", headers=_hdr(roles=_OPERATOR))
    assert r.status_code == 200
    decision = ops.last_for("GET", "/api/traces")[-1]
    assert decision.permission.value == "ops:traces:read"


def test_the_operator_runs_and_then_reads_the_result(ops):
    assert ops.client.get("/api/evals/latest", headers=_hdr(roles=_OPERATOR)).status_code == 404

    r = ops.client.post("/api/evals/run", headers=_hdr(roles=_OPERATOR))
    assert r.status_code == 200, r.text
    assert ops.harness["runs"] == 1

    got = ops.client.get("/api/evals/latest", headers=_hdr(roles=_OPERATOR))
    assert got.status_code == 200
    assert got.json()["run"] == 1
    assert ops.harness["runs"] == 1, "reading must not re-run"


def test_a_failed_run_preserves_the_previous_result(ops, monkeypatch):
    assert ops.client.post("/api/evals/run", headers=_hdr(roles=_OPERATOR)).status_code == 200
    good = ops.client.get("/api/evals/latest", headers=_hdr(roles=_OPERATOR)).json()

    def _boom(*a, **kw):
        raise RuntimeError("harness exploded")

    monkeypatch.setattr(evals_route, "run_evals", _boom)
    with pytest.raises(RuntimeError):
        ops.client.post("/api/evals/run", headers=_hdr(roles=_OPERATOR))

    assert ops.client.get("/api/evals/latest", headers=_hdr(roles=_OPERATOR)).json() == good


def test_a_disabled_deployment_refuses_even_the_operator(ops, monkeypatch):
    """Authorization and the feature gate are independent controls: holding
    `ops:evals:run` does not override an operator switching runs off."""
    from app.core import config

    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "false")
    config.get_settings.cache_clear()

    r = ops.client.post("/api/evals/run", headers=_hdr(roles=_OPERATOR))
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]
    assert ops.harness["runs"] == 0


def test_the_operator_holds_no_tenant_data_access(ops):
    """Running the platform does not include reading what customers stored in it."""
    hdr = _hdr(roles=_OPERATOR)
    q = f"?tenant_id={TENANT}&user_id=alice"
    for url in (
        f"/api/memories{q}",
        f"/api/audit{q}",
        f"/api/evidence/policy{q}",
        f"/api/retention/policies{q}",
        f"/api/loops/runs{q}",
    ):
        assert ops.client.get(url, headers=hdr).status_code == 403, url

    r = ops.client.post(
        "/api/chat",
        json={"tenant_id": TENANT, "user_id": "alice", "message": "hello"},
        headers=hdr,
    )
    assert r.status_code == 403


def test_the_operator_still_needs_a_credential(ops):
    assert ops.client.get("/api/traces").status_code == 401
    assert ops.client.post("/api/evals/run").status_code == 401


# ── the runtime witness gate ─────────────────────────────────────────────────
def test_every_enforced_operational_route_records_a_decision(ops):
    ops.clear()
    urls = {
        ("GET", "/api/traces"): ("get", "/api/traces"),
        ("POST", "/api/evals/run"): ("post", "/api/evals/run"),
        ("GET", "/api/evals/latest"): ("get", "/api/evals/latest"),
        ("GET", "/api/admin/workers/health"): ("get", "/api/admin/workers/health"),
        ("GET", "/api/admin/readiness"): ("get", "/api/admin/readiness"),
    }
    expected = enforced_in(ROUTE_AUTHZ, Status.ENFORCED, is_operational_domain)
    assert set(urls) == expected, f"gate misses an operational route: {set(urls) ^ expected}"

    hdr = _hdr(roles=f"{_OPERATOR} service_worker")
    for route, (verb, url) in urls.items():
        r = getattr(ops.client, verb)(url, headers=hdr)
        assert r.status_code == 200, f"{route}: {r.status_code} {r.text[:160]}"

    witnessed = {d.route for d in ops.decisions}
    assert not expected - witnessed, f"no decision recorded for {sorted(expected - witnessed)}"


@pytest.mark.parametrize("role", _TENANT_ROLES)
def test_no_tenant_role_reads_the_deployment_readiness_report(ops, role):
    """`/readyz` narrows to a boolean in production; the detailed inventory of
    configured backends and providers is an operator's, not a customer's."""
    r = ops.client.get("/api/admin/readiness", headers=_hdr(roles=role))
    assert r.status_code == 403, f"{role}: {r.text}"
    assert "ops:readiness" in r.json()["detail"]


def test_the_operator_reads_the_full_readiness_report(ops):
    r = ops.client.get("/api/admin/readiness", headers=_hdr(roles=_OPERATOR))
    assert r.status_code == 200
    body = r.json()
    assert {"ready", "degraded", "profile", "storage", "checks"} <= set(body)


def test_public_readiness_hides_the_deployment_inventory_in_production(monkeypatch):
    """The disclosure this split closes: an unauthenticated caller learned the
    storage backend, both providers, the embedding dimension and the profile."""
    from fastapi.testclient import TestClient

    from app import deps
    from app.core import config
    from app.db import factory

    def _clear():
        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()

    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    _clear()
    from app.main import app

    client = TestClient(app)
    dev = client.get("/readyz").json()
    assert "storage" in dev and "checks" in dev, "dev keeps the documented 1.x shape"

    # Production also refuses several insecure defaults, so set the ones it requires
    # alongside the profile — this test is about the readiness payload, not startup.
    monkeypatch.setenv("MEMORYOPS_PROFILE", "production")
    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "trusted_header")
    monkeypatch.setenv("MEMORYOPS_CORS_ORIGINS", "https://app.example.com")
    _clear()
    prod = client.get("/readyz")
    assert prod.status_code == 200
    body = prod.json()
    assert set(body) == {"ready", "degraded", "detail"}
    for leaked in ("storage", "llm_provider", "embeddings_provider", "embedding_dim",
                   "profile", "checks"):
        assert leaked not in body, f"{leaked} still disclosed unauthenticated"
    _clear()


def test_the_operational_witness_gate_is_not_vacuous(ops, monkeypatch):
    import app.routes.traces as traces_route

    monkeypatch.setattr(traces_route, "require_permission", lambda request, permission: None)
    ops.clear()
    r = ops.client.get("/api/traces", headers=_hdr(roles="memory_viewer"))
    assert r.status_code == 200, "the unchecked handler still answers normally"
    assert not ops.last_for("GET", "/api/traces"), (
        "no decision recorded — the gate cannot detect a handler that stopped checking"
    )


def test_operational_routes_are_unchanged_with_auth_disabled(api_client):
    client, _repo = api_client
    evals_route.reset_cache()
    assert client.get("/api/traces").status_code == 200
    assert client.get("/api/evals/latest").status_code == 404  # nothing has run yet


# ── the remaining public surfaces ────────────────────────────────────────────
def _fresh_client(monkeypatch, **env):
    from fastapi.testclient import TestClient

    from app import deps
    from app.core import config
    from app.db import factory

    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()
    import importlib

    import app.main as main_module

    importlib.reload(main_module)
    return TestClient(main_module.app)


def test_the_api_schema_is_not_published_in_production():
    """`/openapi.json` enumerates every route, parameter and model — a map of the
    attack surface, served unauthenticated.

    Asserted on the policy rather than by building a production app: production
    refuses to start with the in-memory store, so constructing one here would be
    testing the startup guard instead of the docs decision.
    """
    from app.core.config import Settings

    assert Settings(profile="production").docs_enabled() is False
    assert Settings(profile="dev").docs_enabled() is True


def test_an_operator_can_publish_the_schema_deliberately():
    """A decision, not a lockout — the switch exists so enabling it is explicit, and
    an explicit value wins over the profile in both directions."""
    from app.core.config import Settings

    assert Settings(profile="production", expose_api_docs=True).docs_enabled() is True
    assert Settings(profile="dev", expose_api_docs=False).docs_enabled() is False


def test_the_running_app_wires_the_docs_decision(monkeypatch):
    """The policy is only worth anything if the app actually consults it."""
    import importlib

    import app.main as main_module
    from app.core import config

    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    monkeypatch.setenv("MEMORYOPS_EXPOSE_API_DOCS", "false")
    config.get_settings.cache_clear()
    importlib.reload(main_module)
    assert main_module.app.openapi_url is None
    assert main_module.app.docs_url is None

    monkeypatch.setenv("MEMORYOPS_EXPOSE_API_DOCS", "true")
    config.get_settings.cache_clear()
    importlib.reload(main_module)
    assert main_module.app.openapi_url == "/openapi.json"
    config.get_settings.cache_clear()
    importlib.reload(main_module)


def test_metrics_can_be_gated_on_the_operator_permission(monkeypatch):
    """`/metrics` sits outside `/api/*`, so the scope middleware never covered it.

    Most deployments scrape it from a private network, so the gate is opt-in — but
    where the endpoint is reachable more widely it must be closable without moving it.
    """
    client = _fresh_client(
        monkeypatch,
        MEMORYOPS_AUTH_MODE="trusted_header",
        MEMORYOPS_STORAGE="memory",
        MEMORYOPS_PROTECT_METRICS_ENDPOINT="true",
    )
    assert client.get("/metrics", headers=_hdr(roles="tenant_admin")).status_code == 403
    assert client.get("/metrics", headers=_hdr(roles=_OPERATOR)).status_code == 200


def test_metrics_stays_open_by_default(monkeypatch):
    """Unchanged for the private-network deployments that scrape it today."""
    client = _fresh_client(
        monkeypatch, MEMORYOPS_AUTH_MODE="trusted_header", MEMORYOPS_STORAGE="memory"
    )
    assert client.get("/metrics", headers=_hdr(roles="memory_viewer")).status_code == 200


def test_public_liveness_stays_minimal():
    """`/healthz` and `/healthz/workers` are load-balancer probes: liveness and a
    boolean, with no counts, scope keys, or failure reasons."""
    import importlib

    from fastapi.testclient import TestClient

    import app.main as main_module

    importlib.reload(main_module)
    client = TestClient(main_module.app)

    health = client.get("/healthz").json()
    assert set(health) <= {"status", "version", "uptime_seconds", "metrics_enabled"}

    workers = client.get("/healthz/workers").json()
    assert set(workers) <= {"healthy", "detail"}
    assert "counts" not in workers and "scopes" not in workers
