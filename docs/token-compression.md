# Token Compression & Cost Awareness

MemoryOps treats token cost as a first-class, measured concern. Context
compression is **optional** and runs at the LLM boundary only (ADR-007,
[integrations/headroom.md](integrations/headroom.md)).

## Design

- Interface: `ContextCompressor.compress_context(text, *, trace_id) -> CompressionResult`.
- Default: `NoopCompressor` (transparent, zero savings).
- Optional: `HeadroomCompressor` (`MEMORYOPS_CONTEXT_COMPRESSION=headroom`),
  degrades to no-op on any failure.
- Compresses only the **composed, governed context block** — never the raw user
  message, never pre-policy content, never canonical stored memory.

## Metrics

Each compressed turn produces:

| Field | Meaning |
|-------|---------|
| `original_tokens_estimate` | est. tokens of the composed context |
| `compressed_tokens_estimate` | est. tokens after compression |
| `tokens_saved_estimate` | `original - compressed` (≥ 0) |
| `compression_ratio` | `tokens_saved / original` (fraction saved) |
| `provider` | `noop` or `headroom` |
| `fallback` | true if compression failed and original was used |

Token counts are deterministic estimates (~4 chars/token), suitable for
instrumentation and tests, not billing-exact accounting.

These surface in the chat response `compression` block and in structured
`context_compression` / `context_compression_failed` logs (phase-10 observability).

## Quality risks & eval strategy

- **Risk:** compression drops a detail the model needed. **Mitigation:** compress
  only governed memory context; keep explainability metadata on the uncompressed
  path; default off.
- **Eval strategy:** retrieval/golden evals run with compression *off* (default)
  to keep them deterministic; a future eval can A/B answer quality with
  compression on once a real provider is wired and measured.

## Honest claim

> Headroom integration adds optional token compression and savings
> instrumentation. MemoryOps reports measured/estimated compression savings per
> request. We do **not** claim a fixed headline reduction until our own metrics
> prove it on representative workloads.

## Cost-control roadmap

- Per-tenant token budgets and cost dashboards (extends phase-16 economics).
- Provider-native context caching / KV-cache alignment behind the same interface.
- Cost-per-write and cost-per-retrieval rollups (v0.7 observability + economics).
