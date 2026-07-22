# ADR-027 — Transactional Evidence (atomic mutation + audit, fork-proof chain)

- Status: Accepted (v2.3)
- Date: 2026-07-22
- Supersedes: none
- Related: ADR-004 (audit), ADR-006 (RLS), ADR-012 (worker runtime),
  ADR-024 (enterprise evidence layer)

## Context

The auditability invariant (#7) promised that "every lifecycle action appends an audit
event," and the Enterprise Evidence Layer (ADR-024) made that trail tamper-evident. But
two gaps sat *below* those guarantees — the evidence was stronger than the transaction
boundary underneath it:

1. **Non-atomic mutation + audit.** Each mutation path wrote the memory row and then, as
   a separate operation, recorded the audit event. A process crash between the two could
   persist a memory without its audit event (or an audit event without its mutation),
   leaving the store in a state the evidence layer claims is impossible. A `repo.transaction()`
   primitive existed but was wired into nothing.

2. **Race-prone chain head.** `add_audit` derived the current chain head with `ORDER BY
   created_at DESC LIMIT 1`. Two concurrent audited mutations for the same tenant could
   read the same head and each compute a successor — a **forked** chain, which
   `verify_chain` correctly reports as broken.

A third, adjacent defect: `summarize_runtime_health` called `list_worker_runs()` with no
tenant, which the (correctly) tenant-scoped Postgres method now rejects, so global worker
health always read as "unavailable."

## Decision

Ship **Transactional Evidence**: make the mutation and its evidence a single unit of work,
and make the chain head safe under concurrency — without weakening tenant isolation.

- **Atomic mutation + audit.** Every mutation-plus-evidence path runs inside one
  `repo.transaction(tenant_id, user_id)`: save/update/merge (`write_service.py`),
  approve/reject/archive + manual edit + soft-delete/tombstone (`routes/memories.py`), and
  legal-hold/pin/protect/consent (`routes/retention.py`). The transaction is re-entrant
  (nested repository calls join the active unit of work) and commits once at the end,
  rolling back both sides on any exception. Best-effort network work (embeddings) is
  computed *before* the transaction opens, so a DB unit of work is never held across it.

- **Fork-proof chain head.** A per-tenant `audit_chain_heads` table (migration 011) holds
  exactly one head row per tenant. `add_audit` ensures the row exists (`INSERT ... ON
  CONFLICT DO NOTHING`), locks it with `SELECT ... FOR UPDATE`, links the new event, and
  advances the head — all inside the surrounding transaction. Concurrent audited mutations
  for a tenant now serialize onto one continuous chain. The in-memory backend uses an
  equivalent per-repo lock around the head read-modify-write. The table is RLS-protected
  like every other tenant-scoped table.

- **Operational worker health, fail-closed.** Global worker health is a genuinely
  cross-tenant operator concern, so it reads through an explicit
  `list_worker_runs_operational()` on a **separately authorized** connection
  (`OPERATIONAL_DATABASE_URL`, a monitoring/BYPASSRLS role) — never the request-scoped,
  RLS-enforced engine. When that connection is not configured, the read raises
  `OperationalAccessUnavailable` and the health surface degrades to an actionable
  "operational access not configured" state rather than crashing or silently returning an
  empty (misleadingly healthy) view. Tenant RLS is never relaxed to serve a global view.

## Consequences

- The auditability invariant now holds under partial failure, not just on the happy path.
  Invariant #7 wording is updated accordingly (README, CLAUDE.md).
- Schema moves to `011_audit_chain_heads`; `PostgresRepository` refuses to start until it
  is applied (existing migration-enforcement behavior).
- Proven by `tests/test_transactional_evidence.py` (rollback: neither side survives a
  partial failure; concurrency: 40 parallel appends form one continuous, verifiable
  chain), a delete-route atomicity test in `tests/test_deletion.py`, and an operational
  vs. tenant-scoped isolation test in `tests/test_tenant_isolation.py`.
- Global worker health requires an operational role to be configured; without it the
  surface is explicitly "not configured" (documented in `docs/worker-runtime.md` and
  `docs/api-contracts.md`) rather than falsely healthy.
- This is transaction-boundary correctness, not new cryptography: the chain remains
  *tamper-evident* (ADR-024), and deletion remains soft/tombstoned (ADR-011/018).
