# Phase 9 — Evaluation Systems

**Question:** Golden datasets, LLM-as-judge, regression gates.

## MemoryOps mapping
Deterministic golden + adversarial cases run against an isolated stack. Each case
maps to an invariant (save / drop / block / pending / deleted / isolation /
temporary / archived / retrieve / breakdown). The runner enforces a pass-rate
floor and zero critical failures. v0.3 adds semantic + keyword retrieval,
archived-exclusion, and score-breakdown-present cases. v0.4 adds `structured`
(extraction runs via the validated structured path) and `conflict` (a
contradicting candidate is flagged) cases, plus adversarial structured-secret and
policy-override-injection cases that must still BLOCK. v1.4 adds `leakage` +
`derived_tombstone` (a deleted memory, and any artifact derived from it, must not
influence output). v1.5 makes deletion *measurable*: a poison-memory battery plus
`cross_session_leakage` (fresh-session / reindex-rebuild non-reappearance) and
`expiry_leakage` (retention-expired / consent-withdrawn active memory is gated out
without deletion), a transitive `derived_tombstone` (`chain_depth`), and the whole
leakage family promoted into the critical, release-gating set — every case carries
its own "teeth" (the secret must be *used* before deletion/expiry).

## Gate (must be true to pass)
- A golden set and an adversarial set exist as data, not code.
- The runner exits non-zero on any critical-invariant failure or sub-80% rate.
- Memory/eval changes are required (by the PR gate) to update the cases.

## Evidence
- `evals/golden_memory_cases.json`, `evals/adversarial_cases.json`
- `evals/run_evals.py`, `services/api/app/services/eval_harness.py`
- `services/api/tests/test_retrieval.py::test_eval_harness_runs`
- `services/api/tests/test_deleted_memory_leakage_evals.py` (v1.5 leakage proofs)

## Current result
`python evals/run_evals.py` → 32/32, RESULT: PASS.

## Status: ✅ Implemented (LLM-as-judge is roadmap)
