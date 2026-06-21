# Integration — Headroom token compression

> Optional, non-invasive. MemoryOps runs fully without Headroom installed.
> License: Headroom is Apache-2.0 (https://github.com/chopratejas/headroom).
> MemoryOps reimplements only the *integration adapter*; it does not vendor
> Headroom source.

## What Headroom is

Headroom is an AI context-compression layer that compresses tool outputs, logs,
files, RAG chunks, and conversation history before they reach an LLM, reducing
tokens while aiming to preserve answer quality. It ships library, proxy, MCP, and
agent-wrap modes.

## Why MemoryOps uses it

LLM context is the dominant token cost of a memory system. Headroom gives
MemoryOps an optional cost lever and a measurable savings story — without
changing the memory lifecycle.

## Where it sits

Headroom runs at the **context/LLM boundary only**, after governance:

```text
user message
  → raw safety / PII / policy checks (write path)
  → memory extraction / retrieval / governance
  → context composer (canonical governed block)
  → optional Headroom compression
  → LLM provider
```

### Why it does NOT run before policy

Compression before the policy broker could hide or reshape secrets/PII before the
safety layer inspects them. MemoryOps therefore compresses **only** the composed
context block — built from already-governed, active, tenant-scoped memories — and
**never** the raw user message or any pre-policy content. See ADR-007.

## How to enable

```bash
pip install "headroom-ai[all]"          # optional dependency
export MEMORYOPS_CONTEXT_COMPRESSION=headroom
export HEADROOM_MODE=library            # library | proxy | mcp
export HEADROOM_OUTPUT_SHAPER=0
```

## How to disable

Unset `MEMORYOPS_CONTEXT_COMPRESSION` or set it to `none` (the default). The app
then uses the transparent `NoopCompressor`.

## Fallback behavior

If Headroom is not installed, unavailable, or raises at runtime, the adapter
returns the original context marked `failed=true` and the gateway sends the
**uncompressed** context. Compression never blocks a chat. The response
`compression.fallback` flag and a `context_compression_failed` log record it.

## Security considerations

- Policy broker always sees raw content (compression is read-side only).
- Deleted / wrong-tenant memories are never retrieved → never compressed.
- Temporary chat composes nothing → nothing compressed.
- Explainability metadata (`used_memories`, IDs, score breakdown) is built on the
  uncompressed path and is unaffected by compression.

## Known limitations

- Token counts are deterministic estimates (≈4 chars/token), not provider-exact.
- Compression may alter context wording; only governed memory context is
  compressed, not system instructions.
- Real savings depend on workload; MemoryOps reports *measured/estimated* savings
  per request rather than a fixed headline number.
