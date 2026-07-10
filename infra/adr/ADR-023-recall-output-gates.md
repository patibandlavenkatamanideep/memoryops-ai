# ADR-023 — Recall Gate + Output Gate

- Status: Accepted (v1.9)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-017 (admission gate + usage trace), ADR-018 (tombstone lineage),
  ADR-013 (governance / sensitivity)

## Context

The Context Admission Gate (v1.3) governs one edge: what memory enters the prompt. It
decides admissibility (deleted / expired / consent / tombstone / relevance) but is
**audience-blind** — a high-sensitivity memory that is fine for a private session is
admitted identically into a shared or public one. And nothing governs the *other* edge:
once the prompt is built, a real LLM may ignore instructions, be prompt-injected, or
infer and restate memory that governance deliberately withheld. "Not admitted" is not
the same as "not disclosed."

## Decision

Add two gates that bracket generation.

- **Recall Gate (`app/services/recall_gate.py`)** — audience-aware entry. Each request
  carries an `audience` (`private` | `team` | `public`); the gate re-blocks any
  *admitted* memory whose `sensitivity` exceeds that audience's clearance
  (`private` = low+medium+high, `team` = low+medium, `public` = low). It runs after
  admission / before compose, consumes the admitted `AdmissionRecord`s, and emits a
  `BLOCK_AUDIENCE` decision — reusing the existing Memory Usage Trace, metrics, and
  audit path. Default `private` clears everything, so behavior is unchanged.
- **Output Gate (`app/services/output_gate.py`)** — disclosure control after
  generation. It inspects the answer and flags a disclosure when it shares a
  distinctive contiguous phrase (≥ 4 significant words) with a *protected* (blocked)
  memory, then `redact`s the offending spans (default) or `refuse`s with a safe
  message. Deterministic + no-throw: on any error it returns the answer unchanged; it
  only ever removes information, never adds. Acting is audited (`output_gate_blocked`)
  and surfaced as an `output_gate` block on the response.
- **Additive schema.** `ChatRequest.audience` (default `private`) and an optional
  `ChatResponse.output_gate` — no breaking change. Toggles `MEMORYOPS_RECALL_GATE`,
  `MEMORYOPS_OUTPUT_GATE`, `MEMORYOPS_OUTPUT_GATE_MODE`.

## Consequences

- Governance now controls both edges: what enters context (recall/admission) *and*
  what the answer may reveal (output) — closing the loop the deletion-leakage evals
  (v1.5) measure.
- On by default but no-op for the default `private` audience + an honest model, so all
  prior tests pass unchanged (+9 new). Defense-in-depth: both gates only remove.
- The Recall Gate's blocks flow through the same trace/metrics/audit as admission, so
  they are explainable for free.

## Out of scope (later)

- Semantic / paraphrase-level disclosure detection (an LLM-judge output check) — the
  deterministic gate catches echoed/near-verbatim disclosure only.
- Per-memory ACLs / named audiences beyond the three clearance tiers.
- Coupling `audience` to the v1.6 authenticated principal (e.g. deriving clearance
  from a JWT claim) — the hook exists; wiring it is a later enhancement.
