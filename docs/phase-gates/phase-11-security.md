# Phase 11 — Security Architecture

**Question:** Threat model, prompt injection, Zero Trust, sensitive data.

## MemoryOps mapping
Tenant/user scoping on every query; **enforced** Postgres RLS (v0.3, `FORCE` +
tenant-isolation policy, session GUC `app.tenant_id`); deterministic secret/PII
detection; prompt-injection / memory-poisoning guard; policy-before-storage;
temporary chat; soft-delete with retrieval-exclusion. **Identity + authorization**
(v1.6, ADR-020): an optional, identity-neutral auth layer verifies an
externally-minted identity (trusted upstream header, or a dependency-free bearer-JWT
verify) and enforces that every request's tenant/user matches the authenticated
principal — 401 on missing/invalid creds, 403 on scope mismatch — at the transport
edge, in front of the RLS-backed data layer. Off by default.

## Gate (must be true to pass)
- No read path returns memory across tenants/users.
- Database-level RLS blocks cross-tenant queries even if app filtering fails.
- Secret-like content is blocked before storage; PII elevates sensitivity.
- Injection patterns are blocked.
- The four load-bearing boundaries in SECURITY.md hold.

## Evidence
- `services/api/app/core/redaction.py` (detectors + injection guard)
- `services/api/app/services/policy_broker.py`
- `services/api/app/auth/` (identity providers + scope-validation middleware, v1.6)
- `services/api/tests/test_tenant_isolation.py`, `test_policy_broker.py`, `test_rls.py`, `test_auth.py`
- `infra/db/migrations/004_rls_policies.sql`, `scripts/check_rls_policies.py`
- [SECURITY.md](../../SECURITY.md), [docs/security.md](../security.md), [docs/auth-adapters.md](../auth-adapters.md)
- [ADR-003 policy broker](../../infra/adr/ADR-003-policy-broker.md), [ADR-006 pgvector/RLS](../../infra/adr/ADR-006-pgvector-rls-retrieval.md), [ADR-020 auth adapters](../../infra/adr/ADR-020-auth-authorization-adapters.md)

## Gaps to close (→ later)
- Encryption at rest / KMS; restricted (non-owner) DB role in deployment; session/
  refresh/revocation + live JWKS rotation (front with a proxy or extend the provider).

## Status: ✅ Implemented (v0.3 — RLS enforced; v1.6 — identity + scope authorization; encryption is roadmap)
