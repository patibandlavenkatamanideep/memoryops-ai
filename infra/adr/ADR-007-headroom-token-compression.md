# ADR-007 — Optional Headroom context compression

Status: Accepted (v0.2.1)

## Context
Sending large context blocks to an LLM is the dominant token cost of a memory
system. [Headroom](https://github.com/chopratejas/headroom) (Apache-2.0) is a
context-compression layer that shrinks tool outputs, logs, files, RAG chunks, and
conversation history before they reach an LLM, claiming 60–95% token reduction on
agent workloads. We want that cost lever **without** weakening any MemoryOps
invariant and without making Headroom a hard dependency.

## Decision
Add a `ContextCompressor` interface (`app/compression/`) with:
- `NoopCompressor` — the default, fully transparent (zero tokens saved).
- `HeadroomCompressor` — optional; lazy-imports `headroom`, and on any failure
  (not installed / unavailable / runtime error) returns the original text marked
  `failed=True` so the gateway falls back to the uncompressed context.

Compression runs at exactly one place: in the gateway, **after** retrieval,
governance filtering, and context composition, and **before** the LLM call — and
only on the composed context block, never the raw user message:

```text
user message
  → raw safety / PII / policy checks (write path)
  → memory extraction / retrieval / governance
  → context composer (canonical governed block)
  → optional Headroom compression   ← here
  → LLM provider
```

Canonical memory is never compressed at rest; only the transient context handed
to the LLM is. Enabled via `MEMORYOPS_CONTEXT_COMPRESSION=headroom`.

### Sync, not async
The interface is synchronous to match the synchronous read path (consistent with
the embedding provider in ADR-006). Network/proxy I/O happens inside
`compress_context`; this avoids an async rewrite of the gateway.

## Alternatives
- **Wrap the `claude`/agent CLI with Headroom's proxy** — compresses the *agent's*
  traffic, not MemoryOps' own LLM calls, and would sit outside our governance.
  Rejected for the in-app cost story; still available to operators separately.
- **Provider-native context caching / LiteLLM callbacks** — complementary; can be
  added behind the same interface later.
- **No compression** — the default; always available.

## Trade-offs
- Compression can change wording of the context; we mitigate by compressing only
  governed memory context (not instructions) and by keeping explainability
  metadata (`used_memories`, IDs, score breakdown) on the *uncompressed* path.
- Token counts are deterministic estimates (≈4 chars/token), not a provider
  tokenizer — fine for instrumentation, not billing-exact.

## Security considerations
- **Compression never runs before the policy broker.** The write path (extraction
  → policy → store) sees raw content; compression only touches the read-side
  context block built from already-governed, active, tenant-scoped memories.
- Deleted and wrong-tenant memories are excluded by retrieval, so they are never
  composed and never compressed.
- Temporary chat composes no context, so nothing is compressed.

## Consequences
- New: `app/compression/` (`base`, `noop`, `headroom_adapter`, `metrics`),
  settings, `ChatResponse.compression` metadata, structured
  `context_compression` / `context_compression_failed` logs.
- Tests: `test_context_compression.py`, `test_headroom_fallback.py`,
  `test_compression_invariants.py` — none require a real Headroom install.
- Docs: `docs/integrations/headroom.md`, `docs/token-compression.md`,
  phase-16 (economics) + phase-10 (observability) gates.

## Exit strategy
MemoryOps depends only on the `ContextCompressor` interface, so Headroom can be
replaced by a custom compressor, provider-native context caching, LiteLLM
callbacks, or no compression — without changing memory lifecycle logic.
