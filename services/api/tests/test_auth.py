"""Auth + authorization adapters (v1.6, ADR-020).

Proves the identity layer verifies who the caller is and enforces that every
operation is scoped to the authenticated tenant/user — closing the "we trust
tenant_id/user_id from the body" gap when enabled — while staying a pure no-op when
disabled (default), so no existing behavior changes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.auth import build_provider, decode_jwt
from app.auth.jwt import JWTError
from app.auth.providers import JWTProvider, TrustedHeaderProvider
from app.auth.roles import Role

from ._secret_fixtures import FAKE_JWT_SIGNING_KEY


# ── token minting (independent of app.auth internals, to prove interop) ──────────
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(payload: dict, *, secret: str, alg: str = "HS256") -> str:
    header = _b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    digest = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}[alg]
    sig = _b64(hmac.new(secret.encode(), signing_input, digest).digest())
    return f"{header}.{body}.{sig}"


# ── decode_jwt unit tests ────────────────────────────────────────────────────────
def test_decode_valid_hs256():
    tok = make_jwt({"sub": "u1", "tenant_id": "t1", "exp": time.time() + 60}, secret="s3cr3t")
    payload = decode_jwt(tok, key="s3cr3t", algorithms=["HS256"])
    assert payload["sub"] == "u1" and payload["tenant_id"] == "t1"


def test_decode_rejects_bad_signature():
    tok = make_jwt({"sub": "u1"}, secret="right")
    with pytest.raises(JWTError):
        decode_jwt(tok, key="wrong", algorithms=["HS256"])


def test_decode_rejects_expired():
    tok = make_jwt({"sub": "u1", "exp": time.time() - 3600}, secret="s")
    with pytest.raises(JWTError):
        decode_jwt(tok, key="s", algorithms=["HS256"])


def test_decode_rejects_disallowed_algorithm():
    tok = make_jwt({"sub": "u1"}, secret="s", alg="HS512")
    with pytest.raises(JWTError):
        decode_jwt(tok, key="s", algorithms=["HS256"])


def test_decode_checks_audience_and_issuer():
    tok = make_jwt({"sub": "u1", "aud": "memoryops", "iss": "https://issuer"}, secret="s")
    decode_jwt(tok, key="s", algorithms=["HS256"], audience="memoryops", issuer="https://issuer")
    with pytest.raises(JWTError):
        decode_jwt(tok, key="s", algorithms=["HS256"], audience="other")


def test_decode_rejects_alg_none():
    # An unsigned "alg: none" token must never be accepted (classic JWT attack).
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"sub": "u1", "tenant_id": "t1"}).encode())
    tok = f"{header}.{body}."  # empty signature
    with pytest.raises(JWTError):
        decode_jwt(tok, key="", algorithms=["HS256"])
    with pytest.raises(JWTError):
        decode_jwt(tok, key="", algorithms=["none"])


def test_jwks_unreachable_endpoint_raises_jwterror():
    tok = make_jwt({"sub": "u1"}, secret="s")
    with pytest.raises(JWTError):
        decode_jwt(
            tok, algorithms=["RS256"],
            jwks_url="http://127.0.0.1:1/.well-known/jwks.json",
        )


# ── provider unit tests ──────────────────────────────────────────────────────────
class _Headers(dict):
    def get(self, k, default=None):  # case-insensitive like Starlette
        return super().get(k.lower(), default)


def test_trusted_header_provider():
    p = TrustedHeaderProvider("X-MemoryOps-Tenant", "X-MemoryOps-User")
    ok = p.resolve(_Headers({"x-memoryops-tenant": "t1", "x-memoryops-user": "u1"}))
    assert ok and ok.tenant_id == "t1" and ok.user_id == "u1" and ok.provider == "trusted_header"
    assert p.resolve(_Headers({"x-memoryops-tenant": "t1"})) is None  # missing user


def test_jwt_provider_maps_claims_including_nested():
    tok = make_jwt({"sub": "u1", "app_metadata": {"tenant_id": "t9"}}, secret="s")
    p = JWTProvider(
        key="s", algorithms=["HS256"],
        tenant_claim="app_metadata.tenant_id", user_claim="sub",
    )
    principal = p.resolve(_Headers({"authorization": f"Bearer {tok}"}))
    assert principal and principal.tenant_id == "t9" and principal.user_id == "u1"


def test_jwt_provider_rejects_missing_bearer():
    p = JWTProvider(key="s", algorithms=["HS256"], tenant_claim="tenant_id", user_claim="sub")
    assert p.resolve(_Headers({})) is None


# ── settings-driven provider construction ────────────────────────────────────────
def test_build_provider_none_by_default():
    from app.core.config import Settings

    assert build_provider(Settings()) is None
    assert build_provider(Settings(auth_mode="trusted_header")) is not None
    assert build_provider(Settings(auth_mode="jwt", auth_jwt_key="s")) is not None


# ── end-to-end through the middleware ────────────────────────────────────────────
@pytest.fixture
def auth_client(monkeypatch):
    """Build a TestClient with a given auth env, isolating settings + repo caches."""
    from app import deps
    from app.core import config
    from app.db import factory

    def _make(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()
        from fastapi.testclient import TestClient

        from app.main import app

        return TestClient(app), factory.get_repository()

    yield _make

    config.get_settings.cache_clear()
    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()


def test_auth_off_by_default_no_credentials_needed(auth_client):
    client, _ = auth_client()  # no env → auth_mode none
    r = client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 200


def test_trusted_header_required_and_scoped(auth_client):
    client, _ = auth_client(MEMORYOPS_AUTH_MODE="trusted_header")

    # No identity headers → 401.
    r = client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 401

    hdr = {"X-MemoryOps-Tenant": "t1", "X-MemoryOps-User": "u1"}
    # Matching principal → allowed.
    r = client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hi"}, headers=hdr)
    assert r.status_code == 200

    # Body names a DIFFERENT tenant than the authenticated principal → 403.
    r = client.post("/api/chat", json={"tenant_id": "evil", "user_id": "u1", "message": "hi"}, headers=hdr)
    assert r.status_code == 403


def test_query_param_route_is_scope_enforced(auth_client):
    client, _ = auth_client(MEMORYOPS_AUTH_MODE="trusted_header")
    hdr = {"X-MemoryOps-Tenant": "t1", "X-MemoryOps-User": "u1"}

    # Own scope: allowed (empty list is fine).
    r = client.get("/api/memories?tenant_id=t1&user_id=u1", headers=hdr)
    assert r.status_code == 200

    # Cross-tenant read attempt → 403 before touching the store.
    r = client.get("/api/memories?tenant_id=t2&user_id=u1", headers=hdr)
    assert r.status_code == 403


def test_jwt_mode_end_to_end(auth_client):
    client, _ = auth_client(MEMORYOPS_AUTH_MODE="jwt", MEMORYOPS_AUTH_JWT_KEY="s3cr3t")
    tok = make_jwt({"sub": "u1", "tenant_id": "t1", "exp": time.time() + 60}, secret="s3cr3t")
    auth = {"Authorization": f"Bearer {tok}"}

    r = client.post("/api/chat", json={"tenant_id": "t1", "user_id": "u1", "message": "hi"}, headers=auth)
    assert r.status_code == 200

    # A token for t1 cannot act on t2.
    r = client.post("/api/chat", json={"tenant_id": "t2", "user_id": "u1", "message": "hi"}, headers=auth)
    assert r.status_code == 403

    # A token signed with the wrong key is rejected.
    bad = make_jwt({"sub": "u1", "tenant_id": "t1"}, secret="wrong")
    r = client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "hi"},
        headers={"Authorization": f"Bearer {bad}"},
    )
    assert r.status_code == 401


def test_public_paths_need_no_auth(auth_client):
    client, _ = auth_client(MEMORYOPS_AUTH_MODE="trusted_header")
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200


# ── the roles claim is a container, not a scalar ─────────────────────────────
def test_a_list_roles_claim_is_read_not_discarded():
    """The shape virtually every issuer emits.

    `claim_path` rejects containers on purpose — a tenant or subject that arrived as
    a list is malformed, and `str()`-ing it would invent an identifier. Roles are the
    opposite: an array is the normal shape. Reading them through `claim_path` returned
    `None`, which `resolve_roles` cannot tell apart from an omitted claim, so **every**
    JWT credential fell back to `DEFAULT_ROLE`.

    Both directions were wrong. An `auditor` token silently lost tenant audit access;
    and a token deliberately issued with `roles: []` — the issuer stating this identity
    has no privileges — received `memory_user` instead of nothing, which is
    `memory:read:self`, `memory:write:self` and `memory:delete:self` for a credential
    that was meant to carry none.
    """
    from app.auth.jwt import claim_node, claim_path
    from app.auth.roles import resolve_roles

    payload = {"roles": ["auditor", "memory_admin"], "tenant_id": "t1"}

    assert claim_path(payload, "roles") is None, "unchanged: scalars only"
    assert claim_node(payload, "roles") == (True, ["auditor", "memory_admin"])

    present, raw = claim_node(payload, "roles")
    roles, claim_present = resolve_roles(raw, claim_present=present)
    assert roles == frozenset({Role.AUDITOR, Role.MEMORY_ADMIN})
    assert claim_present is True


def test_an_explicitly_empty_roles_claim_grants_nothing_over_jwt(auth_client):
    """`roles: []` is an authorization decision the issuer already made.

    Under the old reading it became "no claim", and the compatibility fallback handed
    the credential `memory_user`.
    """
    client, _ = auth_client(MEMORYOPS_AUTH_MODE="jwt", MEMORYOPS_AUTH_JWT_KEY="s3cr3t")
    tok = make_jwt(
        {"sub": "u1", "tenant_id": "t1", "roles": [], "exp": time.time() + 60},
        secret="s3cr3t",
    )
    r = client.post(
        "/api/chat",
        json={"tenant_id": "t1", "user_id": "u1", "message": "hi"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403
    assert "memory:write:self" in r.json()["detail"]


def test_a_nested_list_roles_claim_is_read(auth_client):
    """Auth0/Okta-style namespaced claims are nested *and* arrays."""
    from app.auth.jwt import claim_node
    from app.auth.roles import Role, resolve_roles

    present, raw = claim_node({"app_metadata": {"roles": ["tenant_admin"]}}, "app_metadata.roles")
    roles, claim_present = resolve_roles(raw, claim_present=present)
    assert roles == frozenset({Role.TENANT_ADMIN})
    assert claim_present is True


def test_a_scalar_claim_still_refuses_a_container():
    """The narrowing must not leak into tenant/user resolution."""
    from app.auth.jwt import claim_path

    assert claim_path({"tenant_id": ["t1", "t2"]}, "tenant_id") is None
    assert claim_path({"tenant_id": {"id": "t1"}}, "tenant_id") is None
    assert claim_path({"tenant_id": "t1"}, "tenant_id") == "t1"


# ── presence is not the value ────────────────────────────────────────────────
def test_claim_node_separates_presence_from_value():
    """`{"roles": null}` and no `roles` key both hold `None`, and mean opposite things.

    The first is an issuer saying *this identity has no roles*. The second is a
    credential that predates roles entirely. Only the second may take the
    compatibility fallback, and no inspection of the value can tell them apart — which
    is why an explicit `null` kept receiving `DEFAULT_ROLE` even after array claims
    were fixed.
    """
    from app.auth.jwt import claim_node

    assert claim_node({"roles": None}, "roles") == (True, None)
    assert claim_node({}, "roles") == (False, None)
    assert claim_node({"roles": []}, "roles") == (True, [])
    assert claim_node({"app_metadata": {"roles": None}}, "app_metadata.roles") == (True, None)
    assert claim_node({"app_metadata": {}}, "app_metadata.roles") == (False, None)


@pytest.mark.parametrize(
    ("claim", "expected_roles", "expected_present"),
    [
        ({}, frozenset({Role.MEMORY_USER}), False),  # omitted -> fallback
        ({"roles": None}, frozenset(), True),  # explicit null -> nothing
        ({"roles": []}, frozenset(), True),
        ({"roles": ""}, frozenset(), True),
        ({"roles": ["unknown_role"]}, frozenset(), True),
        ({"roles": ["auditor"]}, frozenset({Role.AUDITOR}), True),
    ],
)
def test_every_jwt_role_claim_state_resolves_correctly(claim, expected_roles, expected_present):
    from app.auth.principal import Principal
    from app.auth.providers import JWTProvider

    provider = JWTProvider(
        key=FAKE_JWT_SIGNING_KEY,
        algorithms=["HS256"],
        tenant_claim="tenant_id",
        user_claim="sub",
    )
    tok = make_jwt(
        {"sub": "u1", "tenant_id": "t1", "exp": time.time() + 60, **claim},
        secret=FAKE_JWT_SIGNING_KEY,
    )
    principal = provider.resolve({"authorization": f"Bearer {tok}"})
    assert isinstance(principal, Principal)
    assert principal.role_claim_present is expected_present
    assert principal.effective_roles == expected_roles


def test_a_null_identity_claim_is_rejected_outright():
    """Absent and null are correctly identical for identity claims — there is no
    fallback to reach, so both must refuse authentication rather than invent one."""
    from app.auth.providers import JWTProvider

    provider = JWTProvider(
        key=FAKE_JWT_SIGNING_KEY,
        algorithms=["HS256"],
        tenant_claim="tenant_id",
        user_claim="sub",
    )
    for claims in (
        {"sub": "u1", "tenant_id": None},
        {"sub": None, "tenant_id": "t1"},
        {"tenant_id": "t1"},
        {"sub": "u1"},
    ):
        tok = make_jwt({**claims, "exp": time.time() + 60}, secret=FAKE_JWT_SIGNING_KEY)
        assert provider.resolve({"authorization": f"Bearer {tok}"}) is None, claims


def test_a_trusted_header_still_infers_presence_from_the_header(auth_client):
    """The header provider must keep its own reading: an absent header is `None`,
    an empty header is `""`, and that distinction is already exact."""
    from app.auth.providers import TrustedHeaderProvider

    provider = TrustedHeaderProvider(
        tenant_header="X-MemoryOps-Tenant",
        user_header="X-MemoryOps-User",
        roles_header="X-MemoryOps-Roles",
    )
    base = {"x-memoryops-tenant": "t1", "x-memoryops-user": "u1"}

    absent = provider.resolve(base)
    assert absent.role_claim_present is False
    assert absent.effective_roles == frozenset({Role.MEMORY_USER})

    empty = provider.resolve({**base, "x-memoryops-roles": ""})
    assert empty.role_claim_present is True
    assert empty.effective_roles == frozenset()
