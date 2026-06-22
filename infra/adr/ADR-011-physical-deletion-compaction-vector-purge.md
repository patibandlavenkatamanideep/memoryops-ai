# ADR-011 — Physical Deletion Compaction + Vector-Index Purge Verification

- Status: Accepted (v0.7)
- Date: 2026-06-22
- Supersedes: none
- Related: ADR-005 (deletion guarantee), ADR-006 (pgvector + RLS retrieval),
  ADR-010 (background lifecycle workers)

## Context

v0.6 proves **logical** deletion: a `status='deleted'` memory is unreachable from
active retrieval, default listing, and the vector candidate path, and the deletion
verification worker records auditable evidence of that on every run. But the row's
**bytes are still present** — its content, its embedding/vector material, and its
provenance excerpt all remain in storage. The strongest critique of any memory
system is exactly this: "you *hide* deleted memory, you don't *clear* it."

We want a precise, defensible claim:

> Soft-deleted memory remains unreachable, its retrievable content + vector
> material are cleared where supported, the purge is verified, the governance
> tombstone is preserved, and every step is recorded as audit evidence.

…without overclaiming cryptographic erasure or physical disk-page reclamation,
which depend on the storage/index engine.

## Decision

Add a sixth lifecycle job — **deletion compaction** — plus a **vector purge
verification** layer, both additive and off the chat path.

### Compaction (what changes)

For each soft-deleted memory past a retention/grace window
(`workers_compaction_min_age_days`), the repository clears, in place:

- `content`, `normalized_content`
- the embedding / vector material (in-memory → `[]`; Postgres → vector column
  `NULL`)
- `source.excerpt` (content-bearing provenance excerpt)

and **preserves the tombstone**: memory id, `tenant_id`/`user_id`, `status`
(stays `deleted`), `deleted_at`, `created_at`, `source.kind`, plus the full audit
trail. A content-free marker (`metadata.compaction.*`) records `compacted`,
`compacted_at`, `reason`, and `purge_status`.

### Verification (what is proven)

After compaction, `verify_purged` confirms — **fail-closed** — that the id is
absent from every reachable surface and that content + vector material are
actually cleared and the tombstone is present. Outcomes: `pass`, `fail`,
`skipped`, `not_supported`. A reachable id, intact material, a missing tombstone,
or an error in the verification path itself all yield `fail` — never a silent pass.

### Audit events (content-free)

`deletion_compaction_started/completed/failed/skipped`, `memory_content_compacted`,
`memory_vector_purge_attempted/verified/failed`, `memory_purge_tombstone_preserved`.

### Repository surface (additive only)

`list_deleted_for_compaction` (deleted rows; excludes already-compacted →
idempotent) and `compact_deleted_memory` (no-op-returns-`None` for any row whose
status is not `deleted`). No destructive hard delete; row identity is preserved.

## Honest scope (what this is NOT)

- **Not crypto-shred.** No per-tenant key destruction.
- **Not guaranteed physical disk/page erasure.** Clearing a column does not
  guarantee the database overwrote the underlying pages; that is engine-dependent.
- **Not pgvector reindex/`VACUUM` orchestration.** We clear the vector value; ANN
  index storage reclamation is a separate DBA operation.
- **Not a cross-tenant scheduler.** Scope enumeration stays the orchestrator's job
  (ADR-010).

The accurate claim is *auditable content/vector compaction + retrieval-exclusion
verification with tombstone preservation* — application-level and
repository-level, documented precisely in `docs/vector-purge-verification.md`.

## Alternatives considered

- **Hard `DELETE` of the row.** Rejected: destroys governance evidence (who/when/
  why it was deleted) and the deletion verification trail. Compaction keeps the
  tombstone; a later milestone can stage true hard purge / crypto-shred.
- **Compact on the deletion request path.** Rejected: adds latency to a governed
  action and removes the retention window; compaction belongs off-path with the
  other lifecycle workers.
- **Trust the soft-delete column flip without verification.** Rejected: the whole
  point of v0.7 is *evidence*. Verification is fail-closed.

## Consequences

- Stronger, precise public deletion story; no change to the chat path.
- The runner gains a `deletion_compaction` job; `all` runs it before deletion
  verification so verification observes the compacted state.
- Future work: governed hard purge / crypto-shred, pgvector index compaction
  automation, and fleet-wide scheduling (v0.8 — Railway worker runtime).
