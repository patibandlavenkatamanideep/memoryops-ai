# Deleted / expired memory leakage evals

Most memory systems *claim* deletion. Very few **test** whether a deleted — or merely
expired — memory can still influence output. MemoryOps does, with a deterministic,
offline eval suite (v1.5, [ADR-019](../infra/adr/ADR-019-deleted-memory-leakage-evals.md))
that builds on the tombstone-lineage mechanism from
[v1.4](deletion-proof-lineage.md).

> **not retrievable ≠ cannot influence output** — so every path is a case that runs
> in `run_evals` and the [results dashboard](../apps/results-dashboard/).

## What is proven

| Path | Case kind | What it stores → does → probes |
| --- | --- | --- |
| Direct | `leakage` | store secret → use → **delete** → ask directly → must not surface |
| Indirect / inference | `leakage` | same, probed with "based on my past choices…" style queries |
| Reindex / rebuild | `leakage`, `cross_session_leakage` | re-query after delete never resurrects the row |
| Cross-session | `cross_session_leakage` | delete, then probe from a **brand-new session** (fresh read stack) |
| Summarized / derived | `derived_tombstone` | a summary derived from a deleted memory is blocked |
| Transitive lineage | `derived_tombstone` (`chain_depth`) | deleting the **root** blocks a grandchild summary |
| Expired | `expiry_leakage` (`mode="retention"`) | elapse the retention window → gated out, row still active |
| Consent withdrawn | `expiry_leakage` (`mode="consent"`) | revoke consent → gated out, row still active |

Each case runs against a fresh in-memory stack with no API keys.

## The canonical example

```
1. Store:  "Remember that I prefer Vendor X for all cloud deployments."
2. Ask:    "Which vendor do I usually prefer?"          → uses Vendor X   (teeth)
3. Delete the memory.
4. Ask:    "Which vendor do I usually prefer?"          → must NOT surface
5. Ask:    "Based on my past choices, what should I pick?"  → must NOT surface
6. Ask again from a brand-new session                   → must NOT surface
```

Step 2 is the **teeth**: every case first asserts the secret *was* used before
deletion/expiry, so a pass can never be vacuous.

## Cross-session and reindex/rebuild

`cross_session_leakage` deletes the memory and then probes through a **fresh
`Gateway` built on the same store**. A new Gateway rebuilds the entire read stack
(retriever → ranker → admission gate → composer) from scratch, so this single case
also proves **reindex/rebuild non-reappearance**: the deleted row cannot re-enter
context no matter how the read path is rebuilt.

## Expired vs. deleted

`expiry_leakage` covers memory that is **still an active row** but should no longer
influence output — the retention window has elapsed, or consent was withdrawn. The
[Context Admission Gate](context-admission-gate.md) denies it immediately
(`BLOCK_EXPIRED` / `BLOCK_CONSENT_WITHDRAWN`) — it does **not** wait for the retention
worker to delete the row. The eval asserts the memory is gated out *and* that the row
stays `active` (expiry is a context decision, not a deletion).

## Transitive lineage

`derived_tombstone` accepts a `chain_depth`: it builds a `root → middle → leaf`
lineage chain, confirms the *leaf* summary is used, deletes the **root**, and asserts
the leaf is blocked. This proves the [tombstone-ancestry walk](deletion-proof-lineage.md)
is transitive — a summary of a summary of a deleted memory is still blocked.

## Release gate

The leakage family (`leakage`, `derived_tombstone`, `cross_session_leakage`,
`expiry_leakage`) is in `_CRITICAL_KINDS` in
[`evals/run_evals.py`](../evals/run_evals.py): any leakage regression fails the eval
gate regardless of the overall pass rate.

```bash
# run the whole suite (golden + adversarial, leakage family included)
python evals/run_evals.py

# unit-level proofs, including admission-decision assertions
cd services/api && pytest tests/test_deleted_memory_leakage_evals.py -q
```

## Limits

- We block at the **context boundary**. Physical propagation into prompt caches or
  external vector indices we do not own is out of scope here; our own vector material
  is handled by [deletion compaction](deletion-compaction.md).
- This suite catches leakage *before* prompt composition. Catching leakage *after*
  generation (what the final answer may reveal) is the **Output Gate**, planned for
  v1.9.
