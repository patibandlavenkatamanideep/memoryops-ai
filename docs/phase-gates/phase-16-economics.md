# Phase 16 — Economics & Cost Control

**Question:** Token/cost accounting, compression, budgets, cost-aware context.

## MemoryOps mapping
Context (the retrieved memory block) is the dominant token cost. MemoryOps adds
an optional, governed context-compression layer (Headroom) at the LLM boundary
and instruments per-request token estimates and savings. Compression is off by
default and never weakens an invariant. See ADR-007,
[docs/token-compression.md](../token-compression.md),
[docs/integrations/headroom.md](../integrations/headroom.md).

## Gate (must be true to pass)
- A `ContextCompressor` interface exists; no-op is the default.
- Optional compression runs only after policy/governance/composition.
- App runs with no compression dependency installed.
- Compression failure degrades safely (uncompressed) and never blocks chat.
- Per-request token/savings estimates are reported in the response + logs.
- Cost claims are measured/estimated, not asserted as a fixed headline number.

## Evidence
- `services/api/app/compression/` (`base`, `noop`, `headroom_adapter`, `metrics`)
- `services/api/app/services/gateway.py` (compression at the LLM boundary)
- `services/api/tests/{test_context_compression,test_headroom_fallback,test_compression_invariants}.py`
- [ADR-007 Headroom compression](../../infra/adr/ADR-007-headroom-token-compression.md)

## Gaps to close (→ later)
- Per-tenant token budgets + cost dashboards.
- Cost-per-write / cost-per-retrieval rollups (v0.7 observability + economics).
- Quality A/B evals with a real compression provider.

## Status: ✅ Implemented (v0.2.1 — optional compression + savings instrumentation)
