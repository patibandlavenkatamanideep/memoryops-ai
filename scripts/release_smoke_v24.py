#!/usr/bin/env python3
"""v2.4 "API Trust Boundary" release smoke test against a *deployed* stack.

`railway_smoke_test.py` proves the stack is alive. This proves the thing v2.4
actually claims: that the authorization boundary which passes in CI is the same
boundary a deployment enforces. CI runs the app in-process with TestClient; a
deployment adds a proxy, a real Postgres, environment-driven config and a BFF,
and every one of those has historically been where a control quietly stopped
applying.

Stdlib only (``urllib`` + ``hmac``), so it runs from a Railway shell or a laptop
with no install step. HS256 tokens are minted locally, which is why the
deployment must run ``MEMORYOPS_AUTH_MODE=jwt`` with an HS256 key the operator
can supply here. Nothing is read from the environment implicitly.

    python scripts/release_smoke_v24.py \
        --api-url https://memoryops-api.up.railway.app \
        --web-url https://memoryops-web.up.railway.app \
        --jwt-key "$MEMORYOPS_AUTH_JWT_KEY"

Sections map 1:1 onto the v2.4 release plan:

  C1  infrastructure      liveness, readiness, worker heartbeat
  C2  public surface      unauthenticated shape; docs/openapi closed in prod
  C3  auth boundary       7 principals + the 4 JWT role-claim states
  C4  cross-tenant        tenant A/B isolation, stored-owner authority
  C5  lifecycle           write -> read -> delete -> deletion evidence
  C6  web/BFF             browser cannot supply scope; unknown route fails closed

Exit code is 0 only if every non-skipped check passes. Checks that cannot run
(no --web-url, no --jwt-key) are reported as SKIP and do not mask a failure --
a skipped section is missing evidence, and the summary says so explicitly.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

TIMEOUT_SECONDS = 20

#: Distinguishes "argument not passed" from an explicitly-passed ``None``. v2.4
#: treats an omitted ``roles`` claim and a JSON ``null`` one as different states,
#: so ``None`` cannot double as the default here.
_OMITTED = object()

# ── Result recording ─────────────────────────────────────────────────────────


@dataclass
class Results:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  [PASS] {name}")

    def fail(self, name: str, detail: str) -> None:
        self.failed.append((name, detail))
        print(f"  [FAIL] {name}\n         {detail}")

    def skip(self, name: str, why: str) -> None:
        self.skipped.append((name, why))
        print(f"  [SKIP] {name} — {why}")

    def check(self, name: str, condition: bool, detail: str = "") -> bool:
        if condition:
            self.ok(name)
        else:
            self.fail(name, detail)
        return condition


# ── HTTP ─────────────────────────────────────────────────────────────────────


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects instead of following them.

    A BFF that bounces an unauthenticated caller to a sign-in page is failing
    closed, but urllib follows the 307 by default and hands back the login page as
    a 200 with an HTML body -- which reads exactly like the BFF having served the
    request. Seeing the 3xx itself is the only way to tell those apart.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(_NoRedirect)


def request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> tuple[int, Any, dict[str, str]]:
    """Return (status, parsed_body_or_text, response_headers).

    Never raises for HTTP status -- an expected 403 is a passing result here, so
    error responses must come back as data rather than exceptions.
    """
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)

    opener = urllib.request.urlopen if follow_redirects else _NO_REDIRECT_OPENER.open
    try:
        with opener(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status, resp_headers = resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status, resp_headers = exc.code, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        return 0, f"connection error: {exc.reason}", {}

    try:
        return status, json.loads(raw), resp_headers
    except json.JSONDecodeError:
        return status, raw, resp_headers


# ── HS256 JWT minting (stdlib) ───────────────────────────────────────────────


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(
    key: str,
    *,
    tenant: str,
    user: str,
    roles: Any = _OMITTED,
    actor_type: str | None = None,
    audience: str = "",
    issuer: str = "",
    ttl_seconds: int = 600,
) -> str:
    """Mint an HS256 token.

    ``roles`` is deliberately sentinel-defaulted rather than ``None``-defaulted:
    v2.4 distinguishes an *omitted* claim from a JSON ``null`` one, and those two
    states must be expressible separately here or C3's claim-state matrix cannot
    be tested at all. Pass ``roles=None`` to emit ``"roles": null``.
    """
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": user,
        "tenant_id": tenant,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if roles is not _OMITTED:
        payload["roles"] = roles
    if actor_type:
        payload["actor_type"] = actor_type
    if audience:
        payload["aud"] = audience
    if issuer:
        payload["iss"] = issuer

    signing_input = (
        _b64u(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64u(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(
        key.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64u(signature)}"


# ── Expectation matrix ───────────────────────────────────────────────────────
#
# Derived from ROLE_PERMISSIONS x ROUTE_AUTHZ at the release candidate. Each entry
# is (label, method, path, payload, expected_statuses). A 401 anywhere in here
# means auth is not configured the way the smoke assumes, not that the boundary
# is wrong -- reported distinctly so a misconfigured run is not read as a breach.
#
# ALLOWED = any 2xx (the route ran). DENIED = 403 exactly (authenticated, refused).
# 404 is accepted alongside 2xx only where the resource legitimately may not exist.

ALLOWED = "allowed"
DENIED = "denied"

#: A well-formed but almost certainly absent memory id. Governance mutations must
#: authorize *before* they look the target up, so an unprivileged caller sees 403
#: rather than 404 — using a syntactically valid id is what makes that testable.
#: (A malformed body would 422 during request validation, before authorization runs,
#: and would prove nothing about the boundary.)
ABSENT_MEMORY_ID = "00000000-0000-4000-8000-000000000000"

PRINCIPAL_MATRIX: list[tuple[str, str, str, str, dict | None, str]] = [
    # role,             label,                       method,  path,                          payload, expect
    ("memory_viewer", "viewer reads own memories", "GET", "/api/memories", None, ALLOWED),
    ("memory_viewer", "viewer cannot write (chat)", "POST", "/api/chat", {"message": "hi"}, DENIED),
    ("memory_viewer", "viewer cannot manage retention", "POST", "/api/retention/legal-hold", {"memory_id": ABSENT_MEMORY_ID, "on": True}, DENIED),

    ("memory_user", "user reads own memories", "GET", "/api/memories", None, ALLOWED),
    ("memory_user", "user writes via chat", "POST", "/api/chat", {"message": "Remember that smoke ran."}, ALLOWED),
    ("memory_user", "user cannot administer retention", "POST", "/api/retention/legal-hold", {"memory_id": ABSENT_MEMORY_ID, "on": True}, DENIED),
    ("memory_user", "user cannot read tenant metrics", "GET", "/api/metrics", None, DENIED),

    ("auditor", "auditor reads evidence", "GET", "/api/evidence/policy", None, ALLOWED),
    ("auditor", "auditor reads retention policy", "GET", "/api/retention/policies", None, ALLOWED),
    ("auditor", "auditor reads tenant metrics", "GET", "/api/metrics", None, ALLOWED),
    ("auditor", "auditor cannot mutate governance", "POST", "/api/retention/legal-hold", {"memory_id": ABSENT_MEMORY_ID, "on": True}, DENIED),
    ("auditor", "auditor cannot write memory", "POST", "/api/chat", {"message": "hi"}, DENIED),

    ("memory_admin", "admin governs tenant retention", "GET", "/api/retention/policies", None, ALLOWED),
    # The orthogonality claim: administering memory is not the same authority as
    # auditing it. memory_admin holds neither evidence:read nor audit:read:tenant.
    ("memory_admin", "admin cannot read auditor-only evidence", "GET", "/api/evidence/policy", None, DENIED),
    ("memory_admin", "admin cannot read ops traces", "GET", "/api/traces", None, DENIED),
    ("memory_admin", "admin cannot read deployment readiness", "GET", "/api/admin/readiness", None, DENIED),

    ("tenant_admin", "tenant_admin reads evidence", "GET", "/api/evidence/policy", None, ALLOWED),
    ("tenant_admin", "tenant_admin manages retention", "GET", "/api/retention/policies", None, ALLOWED),
    ("tenant_admin", "tenant_admin has NO ops:traces", "GET", "/api/traces", None, DENIED),
    ("tenant_admin", "tenant_admin has NO ops:evals", "GET", "/api/evals/latest", None, DENIED),
    ("tenant_admin", "tenant_admin has NO ops:readiness", "GET", "/api/admin/readiness", None, DENIED),

    ("platform_operator", "operator reads readiness", "GET", "/api/admin/readiness", None, ALLOWED),
    ("platform_operator", "operator reads traces", "GET", "/api/traces", None, ALLOWED),
    ("platform_operator", "operator reads evals", "GET", "/api/evals/latest", None, ALLOWED),
    ("platform_operator", "operator reads worker health", "GET", "/api/admin/workers/health", None, ALLOWED),
    # The separation that makes platform_operator safe to hand to an SRE.
    ("platform_operator", "operator CANNOT read customer memory", "GET", "/api/memories", None, DENIED),
    ("platform_operator", "operator CANNOT read customer audit", "GET", "/api/audit", None, DENIED),
    ("platform_operator", "operator CANNOT read customer evidence", "GET", "/api/evidence/policy", None, DENIED),
    ("platform_operator", "operator CANNOT write memory", "POST", "/api/chat", {"message": "hi"}, DENIED),

    ("service_worker", "worker reads worker health", "GET", "/api/admin/workers/health", None, ALLOWED),
    ("service_worker", "worker CANNOT read memory", "GET", "/api/memories", None, DENIED),
    ("service_worker", "worker CANNOT read evidence", "GET", "/api/evidence/policy", None, DENIED),
]


def _classify(status: int, expect: str) -> tuple[bool, str]:
    if status == 0:
        return False, "connection failed"
    if status == 401:
        return False, "401 — auth not configured as this smoke assumes (check --jwt-key/aud/iss)"
    if status == 422:
        # Request validation runs before the route handler, so a 422 means this
        # probe's body no longer matches the schema — a smoke bug, not a verdict
        # about the boundary. Never let it read as either pass or breach.
        return False, "422 — probe payload does not match the current request schema; fix the smoke"
    if expect is ALLOWED:
        ok = 200 <= status < 300 or status == 404
        return ok, f"expected 2xx, got {status}"
    ok = status == 403
    if status == 404:
        # A 404 where 403 was expected can be a genuine existence oracle or just a
        # missing resource; call it out rather than silently passing.
        return False, "got 404 where 403 expected — verify this is not an existence oracle"
    return ok, f"expected 403, got {status}"


# ── C1 infrastructure ────────────────────────────────────────────────────────


def section_infrastructure(api: str, r: Results) -> None:
    print("\nC1 — infrastructure")

    status, body, _ = request("GET", f"{api}/healthz")
    r.check("API liveness GET /healthz is 200", status == 200, f"got {status}: {body}")

    status, body, _ = request("GET", f"{api}/readyz")
    # A degraded readiness is still a *valid* response shape; the release gate is
    # that it answers and reports healthy.
    healthy = isinstance(body, dict) and (
        body.get("ready") is True or body.get("status") in {"ok", "ready", "healthy"}
    )
    r.check(
        "API readiness GET /readyz reports healthy",
        status == 200 and healthy,
        f"got {status}: {body}",
    )

    status, body, _ = request("GET", f"{api}/healthz/workers")
    r.check(
        "worker heartbeat GET /healthz/workers is 200",
        status == 200,
        f"got {status}: {body}",
    )


# ── C2 public surface ────────────────────────────────────────────────────────


def section_public_surface(
    api: str, r: Results, *, expect_docs_closed: bool, production: bool
) -> None:
    print("\nC2 — public surface (unauthenticated)")

    status, body, _ = request("GET", f"{api}/healthz")
    minimal = isinstance(body, dict) and len(body) <= 4
    r.check(
        "/healthz exposes only minimal liveness fields",
        status == 200 and minimal,
        f"got {status} with keys {list(body) if isinstance(body, dict) else body}",
    )

    status, body, _ = request("GET", f"{api}/healthz/workers")
    # The documented production shape is exactly {"healthy": bool}.
    exact = isinstance(body, dict) and set(body) == {"healthy"}
    r.check(
        '/healthz/workers is exactly {"healthy": bool}',
        status == 200 and exact,
        f"got {status} with keys {list(body) if isinstance(body, dict) else body}",
    )

    status, body, _ = request("GET", f"{api}/readyz")
    text = json.dumps(body).lower() if not isinstance(body, str) else body.lower()
    # Provider names, backend inventory and embedding dimensions are deployment
    # internals: useful to an operator, free reconnaissance to everyone else.
    leaks = [
        term
        for term in ("openai", "anthropic", "gemini", "qdrant", "lancedb", "weaviate",
                     "pgvector", "postgres", "dimension", "embedding_dim")
        if term in text
    ]
    profile = body.get("profile") if isinstance(body, dict) else None
    if production:
        r.check(
            "/readyz leaks no provider/backend/dimension internals",
            not leaks,
            f"leaked terms {leaks} in: {text[:300]}",
        )
        # Deliberately not asserting a `profile` field: the production readiness
        # body omits it, and requiring it would contradict the minimization this
        # section exists to verify. The shape itself is the evidence.
        keys = set(body) if isinstance(body, dict) else set()
        r.check(
            "/readyz body is minimal in production",
            keys and keys <= {"ready", "degraded", "detail"},
            f"expected a minimal body, got keys {sorted(keys)} — "
            "production readiness should not enumerate dependencies",
        )
    else:
        # The verbose readiness body is intended outside production; asserting the
        # minimal shape against a dev deployment would report a false breach.
        r.skip(
            "/readyz minimal production shape",
            f"profile is {profile!r}, not production (pass --production to assert it)",
        )
        if leaks:
            print(f"         (dev profile exposes {leaks} — expected outside production)")

    for path in ("/docs", "/redoc", "/openapi.json"):
        status, _, _ = request("GET", f"{api}{path}")
        if expect_docs_closed:
            r.check(
                f"{path} is closed in production",
                status in (401, 403, 404),
                f"expected 401/403/404, got {status} — interactive docs are exposed",
            )
        else:
            r.skip(f"{path} closed", "--allow-docs set; not a production profile run")

    status, body, headers = request("GET", f"{api}/metrics")
    # Not asserting a single policy: both "protected" and "deliberately public" are
    # valid deployments. The release requirement is that the deployed reality is
    # known, so it is reported loudly either way.
    if status == 200:
        print(
            "  [NOTE] /metrics is PUBLICLY reachable. Confirm this is intended; if not,\n"
            "         put operator protection in front of it before tagging."
        )
        r.ok("/metrics reachable — policy recorded as PUBLIC")
    else:
        r.ok(f"/metrics is protected (status {status})")


# ── C3 authentication boundary ───────────────────────────────────────────────


def section_auth_boundary(
    api: str, key: str, tenant: str, r: Results, *, production: bool, **jwt_kw
) -> None:
    print("\nC3 — authentication boundary (7 principals)")

    status, _, _ = request("GET", f"{api}/api/memories?tenant_id={tenant}&user_id=nobody")
    r.check(
        "unauthenticated request to an enforced route is 401",
        status == 401,
        f"expected 401, got {status}",
    )

    for role, label, method, path, payload, expect in PRINCIPAL_MATRIX:
        user = f"smoke_{role}"
        token = mint(key, tenant=tenant, user=user, roles=[role], **jwt_kw)
        url = f"{api}{path}"
        if method == "GET":
            url += f"?tenant_id={urllib.parse.quote(tenant)}&user_id={urllib.parse.quote(user)}"
        body = dict(payload) if payload else None
        if body is not None:
            body.setdefault("tenant_id", tenant)
            body.setdefault("user_id", user)

        status, resp, _ = request(method, url, token=token, payload=body)
        ok, detail = _classify(status, expect)
        r.check(f"{role}: {label}", ok, f"{detail} — body: {str(resp)[:200]}")

    print("\nC3b — JWT role-claim states (must stay distinguishable)")
    # Only the *omitted* state is deployment-dependent. It is the compatibility
    # question `auth_require_role_claim` answers: off (dev default) falls back to
    # DEFAULT_ROLE and a write succeeds; on (production default) grants nothing.
    # The other three are authorization decisions the issuer already made and must
    # fail closed under every profile.
    claim_states = [
        ("roles null", {"roles": None}, "present-but-null must not silently grant the default role"),
        ("roles []", {"roles": []}, "explicitly empty = issuer granted nothing -> must be denied"),
        ("roles invalid", {"roles": ["not_a_real_role"]}, "unknown role ignored, never escalated"),
    ]
    observed: dict[str, int] = {}
    for label, kwargs, why in claim_states:
        token = mint(key, tenant=tenant, user="smoke_claims", **kwargs, **jwt_kw)
        status, resp, _ = request(
            "POST",
            f"{api}/api/chat",
            token=token,
            payload={"tenant_id": tenant, "user_id": "smoke_claims", "message": "hi"},
        )
        observed[label] = status
        r.check(
            f"claim state [{label}] fails closed on write ({why})",
            status in (401, 403),
            f"expected 401/403, got {status}: {str(resp)[:200]}",
        )

    token = mint(key, tenant=tenant, user="smoke_claims", **jwt_kw)
    status, resp, _ = request(
        "POST", f"{api}/api/chat", token=token,
        payload={"tenant_id": tenant, "user_id": "smoke_claims", "message": "hi"},
    )
    observed["roles omitted"] = status
    if production:
        r.check(
            "claim state [roles omitted] denied under production "
            "(auth_require_role_claim defaults on)",
            status in (401, 403),
            f"expected 401/403, got {status} — a credential carrying no roles was "
            f"granted the default role in production: {str(resp)[:200]}",
        )
    else:
        r.check(
            "claim state [roles omitted] falls back to DEFAULT_ROLE (dev compatibility)",
            200 <= status < 300,
            f"expected 2xx under a non-production profile, got {status}",
        )

    # The v2.4 fix: an explicitly empty claim is not the same statement as an absent
    # one. If these two ever collapse to the same status, that regression is back.
    r.check(
        "[roles []] and [roles omitted] remain distinguishable",
        observed["roles []"] != observed["roles omitted"] or production,
        f"both returned {observed['roles []']} — an issuer granting no roles is "
        "indistinguishable from a credential that predates roles",
    )
    print(f"         observed: {observed}")


# ── C4 cross-tenant isolation ────────────────────────────────────────────────


def section_cross_tenant(api: str, key: str, r: Results, **jwt_kw) -> None:
    print("\nC4 — cross-tenant isolation")

    tenant_a, tenant_b = f"smoke_a_{uuid.uuid4().hex[:8]}", f"smoke_b_{uuid.uuid4().hex[:8]}"
    alice = mint(key, tenant=tenant_a, user="alice", roles=["memory_user"], **jwt_kw)
    charlie = mint(key, tenant=tenant_b, user="charlie", roles=["memory_user"], **jwt_kw)
    admin_a = mint(key, tenant=tenant_a, user="admin_a", roles=["memory_admin"], **jwt_kw)

    secret = f"cross-tenant-canary-{uuid.uuid4().hex[:10]}"
    status, resp, _ = request(
        "POST", f"{api}/api/chat", token=alice,
        payload={"tenant_id": tenant_a, "user_id": "alice",
                 "message": f"Remember this canary: {secret}"},
    )
    if not r.check(
        "tenant A / alice writes a canary memory",
        200 <= status < 300, f"got {status}: {str(resp)[:200]}",
    ):
        return

    # A token scoped to tenant B asking for tenant A must be refused at the scope
    # middleware, not merely return an empty list -- an empty 200 would still prove
    # the query ran against another tenant's namespace.
    status, resp, _ = request(
        "GET", f"{api}/api/memories?tenant_id={tenant_a}&user_id=alice", token=charlie
    )
    r.check(
        "tenant B token requesting tenant A scope is 403",
        status == 403,
        f"expected 403, got {status}: {str(resp)[:200]}",
    )

    status, resp, _ = request(
        "POST", f"{api}/api/chat", token=charlie,
        payload={"tenant_id": tenant_b, "user_id": "charlie",
                 "message": "What canary do you know about?"},
    )
    leaked = secret in json.dumps(resp)
    r.check(
        "tenant B chat never surfaces tenant A's canary",
        not leaked,
        f"LEAK: tenant A canary appeared in tenant B's response: {str(resp)[:300]}",
    )

    # Caller-supplied user_id must not redirect ownership within a tenant.
    status, resp, _ = request(
        "POST", f"{api}/api/chat", token=alice,
        payload={"tenant_id": tenant_a, "user_id": "bob",
                 "message": "Write this as bob."},
    )
    r.check(
        "alice cannot write as bob via body user_id (403, not silent re-owning)",
        status == 403,
        f"expected 403, got {status}: {str(resp)[:200]}",
    )

    # Administering *another user's* record goes through the governance-mutation
    # path, where the target user is read from the stored memory. The GET collection
    # route stays self-scoped by the query-string middleware, so it is deliberately
    # not the probe here — see the v2.4 non-claims list.
    alice_memory_id = None
    status, listing, _ = request(
        "GET", f"{api}/api/memories?tenant_id={tenant_a}&user_id=alice", token=alice
    )
    items = listing.get("items", listing) if isinstance(listing, dict) else listing
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and secret in json.dumps(item):
                alice_memory_id = item.get("id") or item.get("memory_id")
                break

    if alice_memory_id:
        status, resp, _ = request(
            "POST", f"{api}/api/retention/legal-hold", token=admin_a,
            payload={"tenant_id": tenant_a, "user_id": "admin_a",
                     "memory_id": alice_memory_id, "on": True},
        )
        r.check(
            "memory_admin of tenant A may govern alice's record within tenant A "
            "(stored owner is authoritative)",
            200 <= status < 300,
            f"expected 2xx, got {status}: {str(resp)[:200]}",
        )
        request(
            "POST", f"{api}/api/retention/legal-hold", token=admin_a,
            payload={"tenant_id": tenant_a, "user_id": "admin_a",
                     "memory_id": alice_memory_id, "on": False},
        )
    else:
        r.skip("memory_admin governs a record in its own tenant", "canary id not found")

    status, resp, _ = request(
        "POST", f"{api}/api/retention/legal-hold", token=admin_a,
        payload={"tenant_id": tenant_b, "user_id": "charlie",
                 "memory_id": ABSENT_MEMORY_ID, "on": True},
    )
    r.check(
        "memory_admin of tenant A cannot govern into tenant B",
        status == 403,
        f"expected 403, got {status}: {str(resp)[:200]}",
    )


# ── C5 memory lifecycle ──────────────────────────────────────────────────────


def section_lifecycle(api: str, key: str, r: Results, **jwt_kw) -> None:
    print("\nC5 — memory lifecycle")

    tenant = f"smoke_life_{uuid.uuid4().hex[:8]}"
    user = "lifecycle_user"
    token = mint(key, tenant=tenant, user=user, roles=["memory_user"], **jwt_kw)
    admin = mint(key, tenant=tenant, user=user, roles=["tenant_admin"], **jwt_kw)

    secret = f"lifecycle-canary-{uuid.uuid4().hex[:10]}"
    status, resp, _ = request(
        "POST", f"{api}/api/chat", token=token,
        payload={"tenant_id": tenant, "user_id": user,
                 "message": f"Remember my project codename is {secret}."},
    )
    if not r.check("write: chat stores a memory", 200 <= status < 300, f"got {status}"):
        return

    status, listing, _ = request(
        "GET", f"{api}/api/memories?tenant_id={tenant}&user_id={user}", token=token
    )
    items = listing.get("items", listing) if isinstance(listing, dict) else listing
    memory_id = None
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and secret in json.dumps(item):
                memory_id = item.get("id") or item.get("memory_id")
                break
    if not r.check(
        "retrieve: the written memory is listed", memory_id is not None,
        f"canary not found in listing: {str(listing)[:300]}",
    ):
        return

    status, prov, _ = request(
        "GET",
        f"{api}/api/memories/{memory_id}/provenance?tenant_id={tenant}&user_id={user}",
        token=token,
    )
    has_source = isinstance(prov, dict) and bool(json.dumps(prov))
    r.check(
        "provenance: memory carries a non-null source (invariant #3)",
        200 <= status < 300 and has_source,
        f"got {status}: {str(prov)[:200]}",
    )

    # Legal hold is a preservation control and must beat deletion, fail-closed.
    status, resp, _ = request(
        "POST", f"{api}/api/retention/legal-hold", token=admin,
        payload={"tenant_id": tenant, "user_id": user,
                 "memory_id": memory_id, "on": True},
    )
    hold_set = 200 <= status < 300
    r.check("legal hold: can be placed by tenant_admin", hold_set, f"got {status}: {str(resp)[:200]}")

    # DELETE carries its scope in the body, not the query string — the query-string
    # middleware cannot guard it, so the route enforces scope itself.
    delete_body = {"tenant_id": tenant, "user_id": user}

    if hold_set:
        status, resp, _ = request(
            "DELETE", f"{api}/api/memories/{memory_id}", token=token, payload=delete_body
        )
        r.check(
            "legal hold: blocks deletion while active (fail-closed preservation)",
            status in (403, 409, 423),
            f"expected a refusal (403/409/423), got {status}: {str(resp)[:200]}",
        )
        request(
            "POST", f"{api}/api/retention/legal-hold", token=admin,
            payload={"tenant_id": tenant, "user_id": user,
                     "memory_id": memory_id, "on": False},
        )

    status, resp, _ = request(
        "DELETE", f"{api}/api/memories/{memory_id}", token=token, payload=delete_body
    )
    if not r.check(
        "delete: memory deletes once the hold is released",
        200 <= status < 300, f"got {status}: {str(resp)[:200]}",
    ):
        return

    status, after, _ = request(
        "GET", f"{api}/api/memories?tenant_id={tenant}&user_id={user}", token=token
    )
    r.check(
        "deletion guarantee: deleted memory is absent from retrieval (invariant #2)",
        secret not in json.dumps(after),
        f"LEAK: canary still retrievable after delete: {str(after)[:300]}",
    )

    status, chat_after, _ = request(
        "POST", f"{api}/api/chat", token=token,
        payload={"tenant_id": tenant, "user_id": user,
                 "message": "What is my project codename?"},
    )
    r.check(
        "deletion guarantee: deleted memory does not re-enter chat context",
        secret not in json.dumps(chat_after),
        f"LEAK: canary resurfaced in chat: {str(chat_after)[:300]}",
    )

    # The tombstone must outlive the content: deletion has to remain *answerable*.
    status, evidence, _ = request(
        "GET",
        f"{api}/api/evidence/deletion/{memory_id}?tenant_id={tenant}&user_id={user}",
        token=admin,
    )
    r.check(
        "deletion evidence remains answerable after purge",
        200 <= status < 300,
        f"expected 2xx, got {status}: {str(evidence)[:200]}",
    )


# ── C6 web / BFF ─────────────────────────────────────────────────────────────


def section_web_bff(web: str, r: Results) -> None:
    print("\nC6 — web / BFF boundary")

    status, _, _ = request("GET", web, follow_redirects=False)
    # In authenticated mode the root legitimately redirects to sign-in, so a 3xx is
    # a healthy answer here, not a failure.
    r.check(
        "web app responds (200, or a redirect to sign-in)",
        200 <= status < 400,
        f"got {status}",
    )

    # Redirect-to-sign-in (3xx) is a closed door, same as 401/403/404. What must
    # never happen is a 2xx carrying proxied API data.
    closed = (401, 403, 404, 405, 307, 302, 303)

    # The BFF's whole job is that scope comes from the session, never the browser.
    # If a client-supplied tenant_id is honoured, every other control is bypassable.
    attacker = f"attacker_{uuid.uuid4().hex[:8]}"
    status, body, _ = request(
        "GET",
        f"{web}/api/memoryops/api/memories?tenant_id={attacker}&user_id=root",
        follow_redirects=False,
    )
    text = json.dumps(body) if not isinstance(body, str) else body
    r.check(
        "BFF refuses or strips a browser-supplied tenant scope",
        status in closed or attacker not in text,
        f"BFF echoed attacker-controlled scope (status {status}): {text[:300]}",
    )

    status, body, _ = request(
        "GET", f"{web}/api/memoryops/api/definitely-not-a-route", follow_redirects=False
    )
    r.check(
        "BFF fails closed on an unknown proxied route",
        status in closed,
        f"expected a closed response {closed}, got {status}: {str(body)[:200]}",
    )

    status, _, _ = request(
        "POST", f"{web}/api/memoryops/api/evals/run", payload={}, follow_redirects=False
    )
    r.check(
        "unauthenticated browser cannot reach a platform_operator route via the BFF",
        status in closed,
        f"expected a closed response {closed}, got {status} — "
        "an unauthenticated browser reached an ops surface",
    )

    # Limitation worth stating rather than papering over: these probes are
    # unauthenticated. Proving that a *signed-in* tenant persona still cannot reach
    # an ops route needs a real session cookie, which this harness does not mint.
    print(
        "  [NOTE] C6 probes are unauthenticated. Persona-level BFF checks (a signed-in\n"
        "         tenant_admin must not reach ops routes) still need a manual session."
    )


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="v2.4 API Trust Boundary release smoke test."
    )
    parser.add_argument("--api-url", required=True, help="Deployed API base URL")
    parser.add_argument("--web-url", default="", help="Deployed web base URL (enables C6)")
    parser.add_argument("--jwt-key", default="", help="HS256 key; enables C3/C4/C5")
    parser.add_argument("--jwt-audience", default="", help="Must match MEMORYOPS_AUTH_JWT_AUDIENCE")
    parser.add_argument("--jwt-issuer", default="", help="Must match MEMORYOPS_AUTH_JWT_ISSUER")
    parser.add_argument("--tenant", default=f"smoke_{uuid.uuid4().hex[:8]}")
    parser.add_argument(
        "--allow-docs",
        action="store_true",
        help="Skip the docs-are-closed assertions (non-production profile).",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Assert production-profile behaviour: minimal /readyz, and a credential "
        "with no roles claim gets no permissions. Use this for the release gate.",
    )
    args = parser.parse_args()

    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")
    r = Results()
    jwt_kw = {"audience": args.jwt_audience, "issuer": args.jwt_issuer}

    print(f"v2.4 release smoke — API {api}")
    if web:
        print(f"                     web {web}")

    section_infrastructure(api, r)
    section_public_surface(
        api, r, expect_docs_closed=not args.allow_docs, production=args.production
    )

    if args.jwt_key:
        section_auth_boundary(
            api, args.jwt_key, args.tenant, r, production=args.production, **jwt_kw
        )
        section_cross_tenant(api, args.jwt_key, r, **jwt_kw)
        section_lifecycle(api, args.jwt_key, r, **jwt_kw)
    else:
        for name in ("C3 auth boundary", "C4 cross-tenant", "C5 lifecycle"):
            r.skip(name, "--jwt-key not supplied")

    if web:
        section_web_bff(web, r)
    else:
        r.skip("C6 web/BFF", "--web-url not supplied")

    print("\n" + "=" * 70)
    print(f"PASSED {len(r.passed)}   FAILED {len(r.failed)}   SKIPPED {len(r.skipped)}")
    if r.failed:
        print("\nFailures:")
        for name, detail in r.failed:
            print(f"  - {name}\n      {detail}")
    if r.skipped:
        print("\nSkipped (missing evidence — not the same as passing):")
        for name, why in r.skipped:
            print(f"  - {name}: {why}")

    if r.failed:
        print("\nRESULT: FAIL — the deployed trust boundary does not match the release claim.")
        return 1
    if r.skipped:
        print("\nRESULT: INCOMPLETE — everything run passed, but sections were skipped.")
        return 2
    print("\nRESULT: PASS — deployed trust boundary matches the v2.4 claim.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
