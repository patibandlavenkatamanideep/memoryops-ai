# ADR-026 — Public Memory-Governance Benchmark

- Status: Accepted (v2.2)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-019 (deleted-memory leakage evals), ADR-009-era eval harness,
  ADR-017/018 (admission + lineage)

## Context

MemoryOps' differentiator is that governance is *measured*, not claimed — the eval
harness already runs golden + adversarial + leakage cases. But those results were an
internal pass/fail, not a public, reproducible artifact a prospective user or a
competing memory system could line up against. "Show measurable proof" needs a
benchmark with named suites and a scorecard, not just a green CI check.

## Decision

Ship a **public benchmark** (`benchmark/`) that scores the existing eval harness into
named governance suites.

- **`run_benchmark.py`** reuses `run_evals()` (no new eval logic) and rolls each case
  kind into a suite: `deletion_and_leakage`, `tenant_isolation`, `context_admission`,
  `policy_governance`, `retrieval_quality`. It emits a human scorecard/leaderboard, a
  `--json` machine format, and a committed `SCORECARD.md`.
- **Critical suites** (`deletion_and_leakage`, `tenant_isolation`) must be 100% or the
  benchmark exits non-zero — the core trust story is a hard gate, not a soft average.
- **Every eval kind must map to a suite** (a test asserts no uncategorized kinds), so
  the benchmark can't silently drop coverage as new cases are added.
- **Reproducible + offline**: runs against the deterministic stub stack, no keys.
- **Bring-your-own**: suites are defined by outcome, so another memory system can
  implement the same case kinds and fill in the same table — the "deletion leakage
  leaderboard" is this scorecard per entrant.
- **Domain examples**: an enterprise assistant and a regulated (healthcare/legal/
  finance) demo show the controls end-to-end (governed recall, audience scoping,
  verifiable erasure, tamper-evident audit).

## Consequences

- MemoryOps ships a public, reproducible scorecard (currently 100%, critical suites
  perfect) that anyone can rerun and that competitors can be measured against.
- Additive: new `benchmark/` dir + two SDK examples + a benchmark test; no change to
  the eval harness or the server.
- The benchmark inherits the harness's honesty (every leakage case carries its own
  "teeth" — the secret must be used *before* deletion), so a green scorecard is not
  vacuous.

## Out of scope (later)

- A hosted, versioned public leaderboard site with multiple entrants.
- Latency/cost benchmarking (this measures governance correctness, not performance).
- Standardizing the case-kind schema as an external spec for other systems.
