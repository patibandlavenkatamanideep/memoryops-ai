# ADR-019 — Deleted / Expired Memory Leakage Evals

- Status: Accepted (v1.5)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-018 (tombstone lineage + leakage proof), ADR-017 (admission gate +
  usage trace), ADR-013 (retention / legal hold / consent)

## Context

ADR-018 (v1.4) put the *mechanism* in place — tombstone lineage, a
`BLOCK_TOMBSTONED_ANCESTOR` verdict, and two eval kinds (`leakage`,
`derived_tombstone`). What it did not yet do is make the guarantee **broadly
measurable**. Most memory projects *claim* deletion; very few test whether deleted
memory can still influence output. The field critique — *"not retrievable ≠ cannot
influence output"* — applies to more paths than a single derivation hop:

- a **brand-new session** that never saw the memory (does a fresh read stack, rebuilt
  from the store, leak it back?);
- **expired / consent-withdrawn** memory that is still an *active* row (the retention
  worker deletes it later — until then, is it gated out of context?);
- **multi-level** derivation chains (summary of a summary), where lineage blocking
  must be transitive, not one hop deep;
- a broader **poison-memory battery** across categories (preferences, health,
  financial, identifiers), not just the two demo secrets.

## Decision

Ship a **deleted / expired memory leakage eval suite** that makes each of these a
first-class, deterministic, offline case. No new runtime mechanism is required — the
admission gate + tombstone lineage already enforce the guarantee; v1.5 *proves* it.

- **New eval kind `cross_session_leakage`** (`app/services/eval_harness.py`). Store a
  secret in "session 1", confirm it is used, delete it, then probe from a **fresh
  `Gateway` built on the same store**. A new Gateway rebuilds the entire read stack
  (retriever → ranker → gate → composer) from scratch, so this doubles as the
  **reindex/rebuild non-reappearance** proof. The secret must not surface in used
  content, in the answer, or by id, and the row must never be retrievable again.
- **New eval kind `expiry_leakage`**. Store, confirm used, then either revoke consent
  (`mode="consent"`) or elapse the retention window (`mode="retention"`) via the
  governance helpers — **without deleting the row** — and re-probe. The gate must deny
  admission (`BLOCK_CONSENT_WITHDRAWN` / `BLOCK_EXPIRED`) and nothing may leak, yet the
  row stays `active` (expiry ≠ deletion; the retention worker forgets it later).
- **Transitive `derived_tombstone`.** The existing kind gains an optional
  `chain_depth`: it builds a root → … → leaf lineage chain, confirms the *leaf* is
  used, deletes the **root**, and asserts the leaf is blocked — proving lineage
  blocking walks the whole chain.
- **Poison-memory battery.** Additional `leakage` cases across categories (bank /
  pharmacy / project-codename preferences) alongside the v1.4 vendor + health cases.
- **Release-gating.** `run_evals.py` promotes the leakage family
  (`leakage`, `derived_tombstone`, `cross_session_leakage`, `expiry_leakage`) into
  `_CRITICAL_KINDS`, so any leakage regression fails the eval gate regardless of the
  overall pass rate.
- **Teeth.** Every case first asserts the secret WAS used before deletion/expiry
  (`used_before`), so a pass can never be vacuous; the unit tests
  (`tests/test_deleted_memory_leakage_evals.py`) additionally assert the admission
  *decision* in the Memory Usage Trace, not just the used-memory list.

## Consequences

- Deletion and expiry are now **measured**, not asserted: direct, indirect, inference,
  cross-session, summarized, and reindex/rebuild leakage paths each have a case that
  runs in `run_evals` and the results dashboard.
- Deterministic and offline-safe — the whole suite runs against the stub stack, no
  API keys, fresh in-memory store per case.
- Additive only: no schema change, no chat-path behavior change; the suite exercises
  the existing gate + lineage enforcement.

## Out of scope (later)

- **Output Gate** — catching leakage *after* generation (what the final answer may
  reveal), as opposed to what enters context. Planned for v1.9.
- Physical propagation into prompt caches / external vector indices we do not own
  (blocked at the context boundary; compaction handles our own vector material).
- A public leakage leaderboard / cross-backend leakage runs (v1.7 storage abstraction,
  v2.2 benchmark).
