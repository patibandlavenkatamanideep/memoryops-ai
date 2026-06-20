# Security — MemoryOps AI

Security is a cross-cutting plane, not a feature. This document describes the controls implemented in
Phase 0/1 and the production hardening roadmap.

## Threat model

The most dangerous failures for an AI memory system are:

1. **Cross-tenant / cross-user leakage** — A's memory surfaced to B.
2. **Secret capture** — API keys, passwords, tokens persisted as "memory".
3. **Deletion failure** — a "forgotten" memory still influencing answers.
4. **Silent sensitive storage** — health/financial/identity data stored without consent.
5. **Memory poisoning** — low-utility or adversarial content polluting retrieval.

## Controls implemented (Phase 1)

### Tenant & user isolation (invariant #1)
- Every repository method requires `tenant_id` and `user_id` and filters on them.
- No endpoint returns memory across tenants. Verified by `tests/test_tenant_isolation.py`.
- Postgres schema is **RLS-ready** (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`) so a
  `current_setting('app.tenant_id')` policy can be layered on without code changes.

### Policy-before-storage (invariant #5)
- The Policy Broker runs before the Write Service. Nothing reaches the store unevaluated.

### Secret / PII detection
- Regex + heuristic detectors for: OpenAI-style keys (`sk-...`), AWS keys (`AKIA...`), bearer/JWT
  tokens, generic `api_key=`, passwords, credit-card-like and SSN-like numbers, emails/phones.
- Secret-like content → `BLOCK` (never stored). Identity/contact PII → elevated `sensitivity`.
- See [services/api/app/core/redaction.py](../services/api/app/core/redaction.py).

### Sensitivity & approval
- `sensitivity ∈ {low, medium, high}`. With `require_approval_for_sensitive=true`, sensitive
  memories are stored as `pending` and excluded from retrieval until approved.

### Deletion guarantee (invariant #2)
- `DELETE` is a soft delete: `status='deleted'`, `deleted_at=now()`, plus an audit event.
- Retrieval excludes non-active statuses, so deleted memory can never be retrieved again.

### Temporary chat (invariant #6)
- `temporary_chat=true` short-circuits both read and write — no candidates extracted, none stored,
  none retrieved. Audit records `temporary_chat_skipped`.

### Audit immutability (invariant #7)
- `memory_audit_logs` is append-only by convention (no update/delete endpoints). In production this
  is enforced with a revoked-UPDATE/DELETE grant and/or WORM storage.

## Production hardening roadmap

- Encryption at rest (pgcrypto / disk) + field-level encryption for high-sensitivity content.
- KMS-managed keys with rotation.
- SSO/SAML + SCIM provisioning.
- Full RBAC (user / approver / admin / auditor) and per-role API scopes.
- Data retention policies, legal hold, data export (DSAR), right-to-be-forgotten workflow.
- Regional data residency.
- Postgres Row-Level Security enforced (not just enabled).
- SOC 2 control mapping (access, change management, audit logging, encryption).
- Rate limiting + abuse detection on the gateway.
