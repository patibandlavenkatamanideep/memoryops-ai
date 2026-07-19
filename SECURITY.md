# MemoryOps AI Security Policy

This document describes MemoryOps AI's trust model, the security boundaries the
project treats as load-bearing, and how to report a vulnerability.

## 1. Reporting a vulnerability

Report privately via [GitHub Security Advisories](https://github.com/patibandlavenkatamanideep/memoryops-ai/security/advisories/new).
Do not open public issues for security vulnerabilities.

A useful report includes:
- A concise description and severity assessment.
- The affected component by file path and line range (e.g. `services/api/app/services/policy_broker.py:40-70`).
- Environment details (commit SHA, OS, Python version, storage backend).
- A reproduction against `main`.
- Which trust boundary in §3 is crossed.

## 2. Trust model

MemoryOps AI is a memory governance layer. It assumes:
- The gateway is the entry point. `tenant_id`/`user_id` identify the caller and are
  either attached by a trusted auth layer in front of the API, or verified by the
  built-in identity-neutral auth adapters (`MEMORYOPS_AUTH_MODE=none|trusted_header|jwt`,
  **off by default** — `none`). The adapters verify an externally-minted identity
  (trusted upstream header, or a bearer JWT via PyJWT — HS\* out of the box, RS\*/ES\*/JWKS
  with the `[crypto]` extra) and enforce that every op is scoped to the authenticated
  tenant/user (401 on missing/invalid creds, 403 on scope mismatch). MemoryOps is not
  an auth *product* — it verifies identity and enforces scope; issuing identity stays
  upstream (Clerk/Auth0/Supabase/BYO). See [docs/auth-adapters.md](docs/auth-adapters.md), ADR-020.
- The Postgres/in-memory store is trusted infrastructure. On Postgres, tenant
  isolation is additionally enforced by **forced row-level security** (`FORCE ROW LEVEL
  SECURITY` + a tenant policy in `infra/db/migrations/004_rls_policies.sql`), verified in
  CI against a non-superuser role (`scripts/check_rls_policies.py`). See ADR-006.
- LLM/embedding providers are semi-trusted; their failure must never break safety.

## 3. Load-bearing security boundaries

These are the boundaries we treat as security-critical. A bypass is a vulnerability:

1. **Tenant/user isolation** — `services/api/app/db/*`: every read is scoped by
   `tenant_id` + `user_id`. Cross-tenant retrieval is a critical bug.
2. **Policy-before-storage** — `services/api/app/services/policy_broker.py`: secret/
   injection content must be blocked before the write service runs.
3. **Deletion guarantee** — deleted memories must be unreachable by any read path.
4. **Audit integrity** — `memory_audit_logs` is append-only; no API updates/deletes.

Heuristic detectors (`core/redaction.py`) are defense-in-depth, not a hard
boundary: a missed secret pattern is a bug worth fixing but is backstopped by
sensitivity gating and approvals. Treat the four boundaries above as the
load-bearing ones.

## 4. Non-goals (current phase)

- **Identity issuance** — MemoryOps verifies an externally-minted identity and
  enforces tenant/user scope (see §2); it does not mint sessions, manage password/
  social login, or replace an IdP. Issue identity upstream (Clerk/Auth0/Supabase/BYO).
- Rate limiting / DoS protection (assumed at the edge — reverse proxy / API gateway).
- Encryption at rest / KMS (roadmap — see [docs/security.md](docs/security.md)).

Previously listed here and now **shipped** (no longer non-goals): built-in auth
adapters (JWT/JWKS + trusted-header, off by default — §2, ADR-020) and enforced
Postgres RLS (`FORCE`, CI-verified against a non-superuser — §2, ADR-006).

## 5. Defensive posture

- Dependencies are exact-pinned to limit supply-chain blast radius.
- Logs pass through a secret-redacting formatter.
- CI runs the invariant eval harness; the PR gate flags changes to security-
  sensitive surfaces (see [docs/ai-pr-review-policy.md](docs/ai-pr-review-policy.md)).
