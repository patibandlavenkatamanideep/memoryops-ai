# ADR-024 — Enterprise Evidence Layer

- Status: Accepted (v2.0)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-004 (audit), ADR-011 (deletion compaction), ADR-017 (admission gate),
  ADR-018 (tombstone lineage), ADR-023 (recall/output gates)

## Context

MemoryOps enforces governance well, but a security review or compliance audit needs
more than "trust us": it needs artifacts it can *check*. Two gaps: (1) the audit log is
append-only by convention, but nothing lets a reviewer prove it wasn't edited after the
fact; (2) the governance signals (what was used/blocked for a response, why a memory is
deleted, the decision mix for a scope) are computable internally but not exposed as
review-ready evidence.

## Decision

Add an **Enterprise Evidence Layer** (`app/evidence/`) — a tamper-evident audit chain
plus read-only, tenant-scoped evidence reports.

- **Hash-chained audit (`hashchain.py`).** Every audit event links to the previous one
  in its tenant's chain: `entry_hash = SHA-256(canonical(event) + prev_hash)`, set in
  `repo.add_audit` so *all* audited actions are covered (single choke point). `prev_hash`
  / `entry_hash` are added to `StoredAudit`. `verify_chain` **reconstructs order from the
  links** (not timestamps, so it is robust to same-microsecond ties) and detects edits,
  deletions, insertions, and forks.
- **Evidence reports (`reports.py`).** Per-response **evidence bundle** (`trace_id` →
  every audited action + a bundle hash), **deletion proof** (status / tombstone /
  non-retrievability / deletion audit), **policy report** (decision mix for a scope),
  and **lifecycle export** (one memory's governance + lineage + audit timeline). All
  tenant/user scoped and content-minimizing (previews + ids + decisions, never full
  secrets).
- **API (`routes/evidence.py`).** `GET /api/evidence/{audit/verify, response/{id},
  deletion/{id}, policy, lifecycle/{id}}`, each `enforce_scope`-guarded (v1.6). Reads
  only — never mutates governance.
- **Admin dashboard = these endpoints.** Rather than a new server surface, the JSON
  endpoints are the dashboard's data source (consumable by the existing results
  dashboard or any admin UI).

## Consequences

- Governance becomes **verifiable**: a reviewer can confirm the audit trail is intact,
  pull the evidence behind any response, and hand back a deletion proof for a
  right-to-be-forgotten request.
- Additive + backward compatible: two new `StoredAudit` fields (empty until persisted),
  new read-only routes; all prior tests pass, +8 new. Chaining adds one SHA-256 per
  audit write.
- Tamper-**evidence**, not tamper-**proofing**: detects modification of an append-only
  log; a writer with full DB control can still forge a consistent chain (mitigate by
  pinning the head hash to a WORM store / external notary — out of scope here).

## Out of scope (later)

- External notarization / head-hash anchoring; cryptographic signatures (asymmetric).
- Postgres backend chaining (the hashing helper is backend-agnostic; wiring the SQL
  repository mirrors the in-memory `add_audit` change).
- A bundled admin UI (the endpoints exist; the UI is a consumer).
