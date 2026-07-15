# Assistant SDK + Integration Examples (1.0.0)

> Makes MemoryOps easy to adopt: a typed Python client over the governed HTTP API,
> plus runnable integration examples. The SDK adds **no** governance of its own —
> the server stays authoritative for tenant isolation, policy-before-storage, the
> deletion guarantee, legal hold, consent, and audit. See
> [ADR-014](../infra/adr/ADR-014-assistant-sdk.md).

## Why

Before the stable SDK, MemoryOps was a deep, governed backend, but adopting it meant
hand-writing HTTP calls and remembering to inject the tenant/user scope on every
request. The `memoryops-sdk` 1.0.0 contract closes that gap: construct a client once
with your scope, then call `mo.chat(...)`, `mo.list_memories()`,
`mo.set_legal_hold(...)`.

```text
memoryops-sdk (this) = thin typed client over the governed API
services/api          = the real backend (source of truth for governance)
apps/web              = official product / governance UI
apps/results-dashboard= public evidence/demo dashboard (v0.9)
```

## Where it lives

[`packages/memoryops-sdk/`](../packages/memoryops-sdk):

```text
packages/memoryops-sdk/
  pyproject.toml
  README.md
  memoryops/
    __init__.py
    client.py        # MemoryOpsClient (sync, httpx)
    models.py        # typed response models (keep .raw for forward-compat)
    errors.py        # MemoryOpsError / APIError / NotFoundError / LegalHoldError
  examples/
    quickstart.py
    fastapi_integration.py
    rag_assistant.py
    agent_memory.py
  tests/
    test_client_unit.py   # httpx.MockTransport contract tests
    test_client_e2e.py    # against the real ASGI app (in-process)
```

## Design

- **Scope injection.** `tenant_id` / `user_id` are set at construction and added to
  every body/query, so application code can't accidentally cross scopes.
- **Faithful, not clever.** One method per endpoint; responses parse into small
  dataclasses that always keep the full `.raw` payload so new server fields are
  never dropped.
- **Typed errors.** 404 → `NotFoundError`, 409 (held-memory delete) →
  `LegalHoldError`, other non-2xx → `APIError`.
- **Injectable transport.** Pass any `httpx.Client` (e.g. FastAPI `TestClient`)
  via `http_client=` for in-process testing with no network.
- **One dependency** (`httpx`); sync client; Python ≥ 3.10.

## Coverage

The SDK wraps the full HTTP surface: chat; memory CRUD + audit + provenance;
retention / legal hold / pin / protect / consent / decisions (v0.10); audit;
metrics; loops; and health.

## Examples

- **quickstart** — capture → retrieve → govern → forget in ~20 lines.
- **fastapi_integration** — expose your own `/assistant` endpoint backed by
  governed memory; per-user scope from your auth layer.
- **rag_assistant** — blend governed *user* memory (MemoryOps) with *task*
  knowledge from your own RAG store, then prompt your LLM (stubbed; swap in the
  latest Claude model).
- **agent_memory** — a governed memory *tool* for a tool-using agent (remember /
  recall / forget / withdraw consent), with the agent able to read its own audit
  trail.

## Testing

`test_client_unit.py` uses `httpx.MockTransport` for fast, self-contained contract
tests (request shaping, response parsing, error mapping). `test_client_e2e.py`
binds the SDK to the real FastAPI app in-process (via `TestClient`) so it verifies
the SDK against the **live** contract, including legal-hold-blocks-delete and
consent withdrawal. Both run with `cd packages/memoryops-sdk && pytest -q`.

## Limitations / scope

- Synchronous client only (an async client can follow if needed).
- No bundled auth — pass your own `httpx.Client` with auth headers, or front the
  API with your gateway. MemoryOps' own auth model is on the roadmap.
- The SDK is a client; it cannot weaken server-side governance.
