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
- **Database-level Row-Level Security is enforced (v0.3).** Migration
  `004_rls_policies.sql` applies `FORCE ROW LEVEL SECURITY` plus a tenant-isolation
  policy (`tenant_id::text = current_setting('app.tenant_id', true)`) to
  `memory_records`, `memory_audit_logs`, `memory_feedback`, and `memory_settings`.
  The Postgres repository sets the transaction-local `app.tenant_id` GUC on every
  session, so even a bug in application-level filtering cannot leak across tenants
  (defense in depth). RLS is tenant-scoped; per-user isolation stays in application
  SQL so tenant-wide admin/metrics reads still work.
- Verified by `tests/test_rls.py` (DB-guarded; skips without Postgres) and
  `scripts/check_rls_policies.py`. See [ADR-006](../infra/adr/ADR-006-pgvector-rls-retrieval.md).

### Embeddings & retrieval (v0.3)
- Embeddings come from a swappable `EmbeddingProvider`. The default stub is
  deterministic and offline; the optional OpenAI provider activates only when
  `OPENAI_API_KEY` is set and degrades to the stub on failure — no key is ever
  required to run, and a flaky embeddings API never blocks the read path.
- Vector candidate fetch (`search_candidates`) is tenant+user scoped and excludes
  `deleted`/non-active rows at the source, so deleted and wrong-tenant memories are
  never retrievable.

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

### Loop engineering traces (v0.3.1)
- `loop_runs` / `loop_events` (migration `005_loop_engineering.sql`) store operational lifecycle
  traces tagged with `tenant_id` / `user_id`; `Repository.list_loop_runs` filters by that scope so
  traces never leak across tenants (`test_tenant_isolation.py`).
- Loop metadata is structured and bounded — **no raw secrets, API keys, or full user messages** are
  recorded, only state transitions, reasons, and counts.
- Loop traces are operational evidence, not a retrieval surface: they never re-expose a
  soft-deleted memory (`test_deletion.py::test_loop_traces_do_not_resurrect_deleted_memory`).

### Memory control plane (v0.5)
- The browser control plane is a **read + audited-action** surface only; it never
  writes around the policy/write path, and the policy broker stays authoritative.
- New read routes (`GET /api/memories/{id}`, `/{id}/provenance`, `/{id}/audit`) and
  the `list_audit(memory_id=…)` filter are all tenant + user scoped at the
  repository (`test_tenant_isolation.py`, `test_governance_api.py`).
- Provenance responses are metadata only — no embeddings, keys, or secrets are
  serialized.
- Detail may return a soft-deleted row for forensics, but it always carries
  `status=deleted`; it is never listed as active or rendered as active
  (`test_deletion.py`, `test_governance_api.py`).
- Demo identity (`tenant_demo`/`user_demo`) still comes from `apps/web/lib/api.ts`;
  real auth/session and RBAC remain on the hardening roadmap below.

### Background lifecycle workers (v0.6)
- Workers (`services/api/app/workers/`) run **off the chat path** and are tenant +
  user scoped: each run operates on a single explicit `(tenant_id, user_id)` via
  the repository's scoped methods, so a worker cannot reach another tenant's
  memory (`test_*_worker.py`, `test_lifecycle_worker.py`).
- Workers **never resurrect or modify deleted memory**: mutating jobs read active
  rows only and re-filter `status != deleted`; the deletion verification worker is
  read-only (`test_decay_worker.py`, `test_archive_worker.py`,
  `test_deletion_verification_worker.py`).
- **Deletion verification** continuously confirms soft-deleted memory is absent
  from active retrieval, default listing, and the vector candidate path, recording
  pass/fail evidence (invariant #2). This verifies **logical** forgetting — see
  [deletion-verification.md](deletion-verification.md).
- A worker failure can never block chat: exceptions are caught and recorded as
  `lifecycle_worker_failed`, never raised into a caller (invariant #4).
- Worker audit metadata is content-free (ids / counts / flags only). Reflection is
  proposal-only and **disabled by default**.

### Deletion compaction + vector purge verification (v0.7)
- The **deletion compaction worker** clears a soft-deleted memory's `content`,
  normalized content, embedding/vector material, and provenance excerpt after a
  retention window, while preserving the governance tombstone (id, tenant/user,
  `status='deleted'`, `deleted_at`, `source.kind`) and the full audit trail
  (`test_deletion_compaction_worker.py`, `test_deletion.py`).
- Only `status='deleted'` rows are ever compacted; active/archived memory is never
  touched and deleted memory is never resurrected/reactivated (invariants #1, #2).
- The purge is **verified fail-closed**: a still-reachable id, intact material, a
  missing tombstone, or a verification-path error all record
  `memory_vector_purge_failed` and flag the run — never a silent pass
  (`test_vector_purge_verification.py`).
- Every step is audited content-free: `deletion_compaction_started/completed/
  failed/skipped`, `memory_content_compacted`, `memory_vector_purge_attempted/
  verified/failed`, `memory_purge_tombstone_preserved`.
- **Honest boundary.** v0.7 is auditable content/vector compaction +
  retrieval-exclusion verification at the application + repository level. It is
  **not** crypto-shred, does **not** guarantee physical disk/database-page byte
  erasure, and does **not** orchestrate pgvector reindex/`VACUUM`. See
  [deletion-compaction.md](deletion-compaction.md),
  [vector-purge-verification.md](vector-purge-verification.md), and
  [ADR-011](../infra/adr/ADR-011-physical-deletion-compaction-vector-purge.md).

## Production hardening roadmap

- Encryption at rest (pgcrypto / disk) + field-level encryption for high-sensitivity content.
- KMS-managed keys with rotation.
- SSO/SAML + SCIM provisioning.
- Full RBAC (user / approver / admin / auditor) and per-role API scopes.
- Data retention policies, legal hold, data export (DSAR), right-to-be-forgotten workflow.
- Regional data residency.
- Deploy with a restricted (non-owner) DB role in addition to `FORCE RLS` for layered enforcement.
- SOC 2 control mapping (access, change management, audit logging, encryption).
- Rate limiting + abuse detection on the gateway.
