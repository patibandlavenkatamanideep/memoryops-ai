# ADR-025 — Agent Framework Integrations

- Status: Accepted (v2.1)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-014 (assistant SDK), ADR-023 (recall/output gates)

## Context

To be adopted, MemoryOps has to drop into the agent frameworks teams already use —
LangGraph, LlamaIndex, CrewAI, AutoGen, Semantic Kernel, the OpenAI Agents SDK. The
temptation is a bespoke integration package per framework, which multiplies surface area
and drifts from the governed API. But every one of these frameworks has the *same* shape
of memory need: write a durable fact, read relevant context, forget.

## Decision

Ship **one framework-agnostic adapter + thin per-framework examples**, not six SDKs.

- **`memoryops.GovernedMemory`** — a minimal `remember` / `recall` / `context_for` /
  `answer` / `forget` / `withdraw_consent` surface over `MemoryOpsClient`. It carries an
  `audience` (applied to every recall via the v1.9 Recall Gate) and adds **no**
  governance — the server stays authoritative.
- **`GovernedMemory.for_audience(...)`** — a per-agent clearance view over one store, so
  a customer-facing agent (`public`) and an internal agent (`private`) share memory but
  see different subsets.
- **`MemoryOpsClient.chat(..., audience=...)`** — additive SDK parameter wiring the
  request-level audience through.
- **Per-framework examples** (`packages/memoryops-sdk/examples/integrations/`) — each
  wraps `GovernedMemory` into that framework's memory/tool/plugin interface,
  import-guarded (the framework package is optional) and illustrative.
- **The adapter is tested** against the real in-process app
  (`tests/test_integrations.py`), so the glue provably routes through the governed
  pipeline; the per-framework files are documentation-grade (frameworks aren't CI deps).

## Consequences

- Adding a framework is a ~30-line example, not a package. Governance is inherited, not
  re-implemented.
- Additive + backward compatible: one optional SDK parameter, a new module + examples;
  existing SDK tests pass, +5 new adapter tests.
- The examples double as the copy-paste onboarding for each ecosystem.

## Out of scope (later)

- Published, versioned per-framework integration packages on PyPI.
- Deep framework features (LangGraph checkpointer internals, LlamaIndex node
  postprocessors) beyond the memory seam.
- Async client / streaming tool responses.
