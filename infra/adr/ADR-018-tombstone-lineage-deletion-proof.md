# ADR-018 — Tombstone Lineage + Deleted-Memory Leakage Proof

- Status: Accepted (v1.4)
- Date: 2026-07-02
- Supersedes: none
- Related: ADR-017 (admission gate + usage trace), ADR-011 (deletion compaction),
  ADR-013 (retention / legal hold / consent), ADR-004 (audit)

## Context

The deletion guarantee (invariant #2) is simple for a single row — a soft-deleted
memory is never retrieved — and the repository already enforces that at the source.
It gets hard once a memory has **derived artifacts**: a summary consolidated from
it, a compressed context built from that summary, a reflection memory, an episodic
consolidation. Deleting the *source* row does not stop a derived artifact from
carrying the deleted information back into context. Field feedback framed this
precisely: *"not retrievable ≠ cannot influence output."* We had no way to prove
that deleted/expired memory cannot influence output *indirectly*, and no lineage to
propagate a deletion through derived artifacts.

Today the reflection worker is proposal-only (it never authors derived memory), so
persisted derived artifacts do not exist *yet* — but the moment consolidation lands
(source `kind='reflection'` linking source ids), the leak becomes real. This ADR
puts the lineage + enforcement + proof in place ahead of that.

## Decision

Add **tombstone lineage** and a **deleted-memory leakage eval suite**.

- **Lineage metadata (`app/db/lineage.py`).** Content-free lineage lives in the
  memory's `metadata.lineage` jsonb (same pattern as governance state / the
  compaction tombstone): `parent_memory_ids`, `lineage_root_id`, `source_event_id`,
  and an explicit `tombstoned` marker (`tombstoned_at` / reason). `set_lineage` /
  `derived_metadata` record a derivation; `set_tombstone` stamps the marker.
- **Fail-closed ancestry rule.** A derived artifact may not enter context if *any*
  ancestor in its lineage is tombstoned, where an ancestor counts as tombstoned when
  it is soft-deleted (`status='deleted'`), carries the explicit marker, or **can no
  longer be found** (purged / unknown id). "Can't prove it's safe" ⇒ block.
  `ancestry_tombstone` walks the parent lineage transitively, cycle- and depth-safe.
- **Enforced by the admission gate (extends ADR-017).** A new verdict
  `BLOCK_TOMBSTONED_ANCESTOR` is added to the Context Admission Gate. The gateway
  passes a tenant/user-scoped `ancestor_lookup` (which resolves soft-deleted rows
  too), so a memory derived from a deleted ancestor is denied context admission and
  shows up in the Memory Usage Trace with its reason. Defense-in-depth: it only ever
  *removes* memory; without a resolver the check is skipped (backward compatible).
- **Deletion stamps the tombstone.** The `DELETE /api/memories/{id}` route stamps
  the explicit, audited tombstone marker alongside the soft-delete, so propagation
  is independent of *how* a row was deleted and is visible in the audit trail.
- **Leakage eval suite (`app/services/eval_harness.py` + `evals/`).** Two new case
  kinds run in the real eval harness: `leakage` (store a secret → confirm used →
  delete → probe with direct, indirect, and inference-style queries plus a
  re-query/reindex → the secret must not appear in used content or the answer, and
  the deleted row must never resurface) and `derived_tombstone` (an artifact derived
  from a deleted memory must be blocked from context). Cases ship in
  `adversarial_cases.json` so they surface in `run_evals` and the results dashboard.

## Consequences

- The deletion guarantee now provably extends to *derived* artifacts, closing the
  "not retrievable ≠ cannot influence output" gap before consolidation ships.
- Deterministic and offline-safe: leakage cases run against the stub stack, no keys.
- Lineage only ever makes the system more conservative; it never resurrects or
  promotes memory and never bypasses the policy broker (#5).
- Cost is one extra ancestry walk per *derived* candidate at admission time
  (originals — the common case — have no parents and skip it entirely).

## Out of scope (later)

- Physical propagation into prompt caches / external vector indices we do not own
  (we block at the context boundary; compaction handles our own vector material).
- Authoring consolidated/reflection memory (still proposal-only; when it lands it
  will use `derived_metadata` to stamp lineage at creation).
- Recall Gate / Output Gate / audience-aware memory (v1.5, next phase).
