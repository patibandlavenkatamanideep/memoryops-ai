"""Machine-enforced tenant/user scope coverage (invariant #1, P2.3).

The query-string auth middleware guards scope for routes that take tenant_id/user_id
as query params. Routes that carry scope in the request *body* are invisible to that
middleware and must call ``enforce_scope`` themselves. History shows this is easy to
forget (memories PATCH/DELETE did), so this meta-test fails if any mutating `/api/*`
route whose body model has a ``tenant_id`` field does not enforce scope — turning the
invariant from developer discipline into a test.
"""

from __future__ import annotations

import inspect
import re

import pytest
from pydantic import BaseModel

from app.main import app


def _api_routes():
    for r in app.routes:
        if getattr(r, "path", "").startswith("/api/") and getattr(r, "endpoint", None):
            yield r


def _body_scope_model(endpoint) -> type[BaseModel] | None:
    """The route's request-body model, if it carries tenant scope.

    ``eval_str=True`` resolves the string annotations produced by
    ``from __future__ import annotations`` back to the real classes.
    """
    try:
        params = inspect.signature(endpoint, eval_str=True).parameters
    except (NameError, TypeError):  # pragma: no cover — unresolvable annotation
        params = inspect.signature(endpoint).parameters
    for p in params.values():
        ann = p.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel) and "tenant_id" in ann.model_fields:
            return ann
    return None


def _enforces_scope(endpoint) -> bool:
    """True if the endpoint, or a same-module helper it calls, calls enforce_scope."""
    try:
        src = inspect.getsource(endpoint)
    except OSError:  # pragma: no cover
        return False
    if "enforce_scope" in src:
        return True
    module = inspect.getmodule(endpoint)
    for name in set(re.findall(r"\b(_[A-Za-z_]+)\s*\(", src)):  # helper-looking calls
        helper = getattr(module, name, None)
        if callable(helper):
            try:
                if "enforce_scope" in inspect.getsource(helper):
                    return True
            except OSError:  # pragma: no cover
                continue
    return False


def test_body_scoped_routes_enforce_scope():
    offenders = []
    for r in _api_routes():
        if not (r.methods and r.methods & {"POST", "PUT", "PATCH", "DELETE"}):
            continue
        if _body_scope_model(r.endpoint) is None:
            continue
        if not _enforces_scope(r.endpoint):
            offenders.append(f"{sorted(r.methods)} {r.path} ({r.endpoint.__name__})")
    assert not offenders, (
        "body-scoped routes that do not enforce tenant scope (invariant #1): "
        + "; ".join(offenders)
    )


# ── behavioral proof: the memories body routes reject cross-tenant scope under auth ──

@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "trusted_header")
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    client = TestClient(app)
    yield client
    get_settings.cache_clear()


_PRINCIPAL_A = {"X-MemoryOps-Tenant": "tenant_a", "X-MemoryOps-User": "user_a"}


def test_delete_rejects_cross_tenant_body(auth_client):
    # Authenticated as tenant_a but the body names tenant_b → 403, not 404/200.
    resp = auth_client.request(
        "DELETE", "/api/memories/some-id",
        json={"tenant_id": "tenant_b", "user_id": "user_b"},
        headers=_PRINCIPAL_A,
    )
    assert resp.status_code == 403


def test_patch_rejects_cross_tenant_body(auth_client):
    resp = auth_client.patch(
        "/api/memories/some-id",
        json={"tenant_id": "tenant_b", "user_id": "user_b", "status": "archived"},
        headers=_PRINCIPAL_A,
    )
    assert resp.status_code == 403
