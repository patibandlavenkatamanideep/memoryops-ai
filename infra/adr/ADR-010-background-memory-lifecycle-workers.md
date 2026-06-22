# ADR-010 — Background Memory Lifecycle Workers

- Status: Accepted (v0.6)
- Date: 2026-06-21
- Supersedes: none
- Related: ADR-003 (policy broker), ADR-004 (observability), ADR-005 (deletion
  guarantee), ADR-008 (provider LLM adapters), ADR-009 (memory control plane)

## Context

Through v0.5 every memory state change happened on the synchronous chat request
path (capture → policy → store) or via an explicit governance action in the
control plane. Nothing maintained memory *after* it was written: stale memory
kept its importance forever, no process confirmed the deletion guarantee held
over time, and conflicting memories were only detected (advisory) at write time
for the single new candidate, never across the existing corpus.

The lifecycle in the product brief is **Capture → Evaluate → Store → Retrieve →
Rank → Compose → Update → Forget → Audit**. The *Update / Forget* arc needs a
maintenance layer that runs outside the request path. It must not weaken any of
the seven invariants.

## Decision

Introduce a background worker layer in `services/api/app/workers/` with five
jobs, an explicit tenant/user-scoped runner, and structured results:

1. **Decay** — reduce importance of old / low-confidence active memory toward a
   floor; demotes rather than deletes.
2. **Archive** — set stale, not-recently-used, non-pinned active memory to
   `archived` (recoverable, excluded from active retrieval).
3. **Deletion verification** — read-only confirmation that soft-deleted memory is
   absent from every reachable retrieval surface; records pass/fail evidence.
4. **Conflict scan** — reuse the v0.4 advisory conflict detection across the
   active corpus to produce *review candidates*; never overwrites.
5. **Reflection** — proposal-only, **disabled by default**; flags clusters of
   low-importance memory for consolidation without writing or deleting anything.

### Design constraints (non-negotiable)

- **Tenant scoped.** A worker only ever reads/writes through the repository's
  `(tenant_id, user_id)`-scoped methods. Scope is always explicit; the runner is
  handed a single scope. Cross-scope enumeration/scheduling is the orchestrator's
  job, not the worker's (invariant #1).
- **Idempotent + retry-safe.** Bookkeeping markers live under
  `metadata.lifecycle.*`; once a memory is processed a re-run skips it. Running
  any job twice converges (no double-decay, no re-archive).
- **Never resurrect deleted memory.** Mutating workers read active rows only and
  defensively re-filter `status != deleted`. Deletion verification is read-only.
- **Policy broker stays authoritative.** Workers may *demote, archive, flag, or
  propose*. They never bypass policy to create or promote active memory.
  Reflection's eventual write path (deferred) lands as `pending` for governance.
- **Audit everything.** Every run emits `lifecycle_worker_started` /
  `_completed` / `_failed`; every action emits a typed event (invariant #7).
  Audit metadata carries ids/counts/flags only — never raw memory content.
- **Never blocks chat.** Workers are off the request path. The base class catches
  all exceptions, records `lifecycle_worker_failed`, and returns a failed result
  rather than raising (invariant #4).

### Logical vs physical forgetting

This layer verifies **logical** deletion (soft-deleted rows are unreachable). It
does **not** perform physical row/vector purge or cryptographic erasure. Physical
vector compaction and crypto-shred are staged for a later milestone (see
`docs/deletion-verification.md`). Verification gives auditable evidence today
without the operational risk of destructive index surgery.

## Alternatives considered

- **Decay on the read path.** Rejected: adds latency and coupling to chat, and
  makes maintenance non-idempotent and hard to audit.
- **A new repository scope-enumeration method** so workers self-discover all
  tenants. Rejected for v0.6: it widens the `db/` surface (and its isolation /
  deletion guarantees) for an orchestration concern. Kept explicit-scope instead;
  the Railway `worker` service owns scheduling.
- **Auto-merging conflicts / auto-writing reflections.** Rejected: violates
  "policy broker authoritative" and risks silent data loss. Both are
  proposal-only.

## Consequences

- New, isolated module with no changes to the chat request path or the `db/`
  layer; existing v0.5 governance UI and APIs are unaffected.
- The runner doubles as a scheduled health check (non-zero exit on a failed job
  or a deletion-verification finding).
- Configuration via `Settings.workers_*` (thresholds) and the public
  `MEMORYOPS_WORKERS_REFLECTION` toggle.
- Future work: physical vector compaction / crypto-shred worker, scope
  enumeration for fleet scheduling, and a governed reflection write path.
