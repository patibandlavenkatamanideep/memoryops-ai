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
