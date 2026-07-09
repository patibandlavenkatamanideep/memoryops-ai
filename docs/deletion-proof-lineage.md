# Deletion proof — tombstone lineage + leakage evals

Deleting a memory row is easy. Proving a deleted memory **cannot influence output**
— directly *or* through a summary, consolidation, or other derived artifact — is the
hard part (v1.4, [ADR-018](../infra/adr/ADR-018-tombstone-lineage-deletion-proof.md)).

> **not retrievable ≠ cannot influence output** — so MemoryOps tests both.

## Tombstone lineage

Every memory can record where it was **derived from**. Lineage lives content-free in
`metadata.lineage` (same pattern as [governance state](governance.md) and the
compaction tombstone):

```json
{ "lineage": {
    "parent_memory_ids": ["mem_source"],
    "lineage_root_id": "mem_source",
    "source_event_id": "evt_123",
    "tombstoned": false, "tombstoned_at": null, "tombstone_reason": null } }
```

- Originals (a normal chat-captured memory) have **no parents** and skip lineage
  checks entirely.
- Derived artifacts (e.g. a future consolidation with `source.kind="reflection"`)
  record their `parent_memory_ids` via `lineage.set_lineage()` /
  `lineage.derived_metadata()`.
- Deleting a memory stamps an explicit, audited **tombstone** marker in addition to
  the soft-delete.

## Fail-closed ancestry rule

> A derived artifact may not enter context if **any** ancestor in its lineage is
> tombstoned.

An ancestor counts as tombstoned when it is:
- soft-deleted (`status='deleted'`), **or**
- explicitly tombstoned, **or**
- **missing** — purged or an unknown id ("can't prove it's safe" ⇒ block).

`lineage.ancestry_tombstone()` walks the parent chain transitively (cycle- and
depth-safe). The [Context Admission Gate](context-admission-gate.md) enforces it:

```
Memory A: "User prefers Vendor X"           (source)
Summary B  derived_from → A
Context C  derived_from → B

delete A  ⇒  A tombstoned
          ⇒  B blocked (parent A tombstoned)      → BLOCK_TOMBSTONED_ANCESTOR
          ⇒  C blocked (ancestry contains a tombstone)
```

The gate adds one verdict — `BLOCK_TOMBSTONED_ANCESTOR` — which appears in the
Memory Usage Trace (`memories_blocked`) with the offending ancestor id. It only ever
*removes* memory from context (defense-in-depth) and, like the rest of the gate, is
no-throw. The gateway supplies a tenant/user-scoped `ancestor_lookup` that resolves
soft-deleted rows, so ancestry is checked against the real store.

## Deleted-memory leakage evals

Two case kinds run in the real eval harness (`app/services/eval_harness.py`, cases
in `evals/adversarial_cases.json`), so they show up in `run_evals` and the results
dashboard:

| Kind | What it proves |
|------|----------------|
| `leakage` | Store a secret → confirm it is used → delete it → probe with **direct**, **indirect**, and **inference** queries, plus a re-query (reindex sim). The secret must not appear in used-memory content **or** the answer, and the deleted row must never resurface. |
| `derived_tombstone` | An artifact **derived** from a deleted memory must be blocked from context, and the secret must not surface in the answer. |

Example `leakage` case:

```json
{ "id": "adv-leakage-vendor-direct-indirect-inference", "kind": "leakage",
  "save_message": "Remember that I prefer Vendor X for all cloud deployments.",
  "secret_substring": "Vendor X",
  "probe_queries": [
    "Which vendor do I usually prefer?",
    "Based on my past choices, what cloud vendor should I pick?",
    "Can you infer which cloud provider I liked before?" ] }
```

## Scope

- We block at the **context boundary** (admission time). Physical purge of our own
  content + vector material is handled separately by deletion compaction
  ([deletion-compaction.md](deletion-compaction.md)); we do not claim to reach into
  prompt caches or external indices we don't own.
- Authoring consolidated/reflection memory is still proposal-only; when it lands it
  will stamp lineage at creation via `lineage.derived_metadata()`.
