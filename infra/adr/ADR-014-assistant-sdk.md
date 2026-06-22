# ADR-014 — Assistant SDK + Integration Examples

- Status: Accepted (v0.11)
- Date: 2026-06-22
- Supersedes: none
- Related: ADR-013 (retention/legal hold/consent), ADR-009 (memory control plane)

## Context

Through v0.10 MemoryOps exposed a complete governed HTTP API, but the only way to
adopt it was to hand-write `httpx`/`requests` calls and remember to attach the
`tenant_id` / `user_id` scope to every request. That is a real adoption tax and an
easy place to introduce a cross-scope bug. The roadmap's v0.11 goal is to make
MemoryOps easy for other builders to use.

## Decision

Ship a thin, typed **Python SDK** (`packages/memoryops-sdk`) plus runnable
integration examples.

- **`MemoryOpsClient`** wraps the full HTTP surface (chat; memory CRUD + audit +
  provenance; retention / legal hold / consent / decisions; audit; metrics; loops;
  health) and injects the tenant/user scope on every call.
- **The server stays authoritative.** The SDK performs no governance of its own —
  tenant isolation, policy-before-storage, the deletion guarantee, legal hold,
  consent, and audit are all enforced by the API. A client cannot weaken them.
- **Forward-compatible models.** Responses parse into small dataclasses that retain
  the full `.raw` payload, so new server fields are never lost.
- **Typed errors** map governance outcomes: `LegalHoldError` for a 409 held-memory
  delete, `NotFoundError` for 404, `APIError` otherwise.
- **Injectable transport.** Any `httpx.Client` (including FastAPI `TestClient`)
  can be passed in, enabling in-process tests against the real app with no network.
- **One dependency** (`httpx`); sync; Python ≥ 3.10. Examples cover a FastAPI
  integration, a RAG assistant, and an agent-memory tool.

## Consequences

- Adoption drops to a few method calls; the scope-injection design removes a class
  of cross-tenant bugs in caller code.
- The SDK is **additive** — it lives in `packages/`, ships independently, and
  changes no `services/api` code, so it arms no core invariant gate rules. Existing
  backend tests are unaffected.
- Out of scope for v0.11: an async client, bundled auth (callers supply their own
  `httpx.Client`/headers; MemoryOps auth is a later milestone), and SDKs for other
  languages.

See [docs/assistant-sdk.md](../../docs/assistant-sdk.md) and
[packages/memoryops-sdk/README.md](../../packages/memoryops-sdk/README.md).
