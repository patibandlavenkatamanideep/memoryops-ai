# MemoryOps AI — Python SDK (1.0.0)

A small, typed Python client for the [MemoryOps AI](../../README.md) API. It makes
the governed memory lifecycle — capture, retrieve, govern, forget, audit — a few
method calls, while the **server stays the source of truth** for tenant isolation,
policy-before-storage, the deletion guarantee, legal hold, consent, and audit.

> The SDK is a thin, faithful client over the HTTP API. It adds no governance of
> its own — it just makes the governed API easy to call from assistants, agents,
> and RAG apps.

## Install

```bash
pip install memoryops-sdk
# or, from this repo:
pip install -e packages/memoryops-sdk
```

Only dependency: `httpx`.

## Quickstart

Run a MemoryOps API (no infra needed):

```bash
cd services/api && MEMORYOPS_STORAGE=memory uvicorn app.main:app --reload
```

```python
from memoryops import MemoryOpsClient

with MemoryOpsClient("http://localhost:8000", "tenant_demo", "user_demo") as mo:
    # Capture (governed write)
    mo.chat("Remember I prefer metric units and dark mode.")

    # Retrieve (later turns get the governed memory context)
    answer = mo.chat("What units should I use?")
    print(answer.assistant_message)
    print([u.content for u in answer.used_memories])

    # Inspect
    for m in mo.list_memories():
        print(m.memory_type, m.content, m.status)
```

The `tenant_id` and `user_id` you pass to the constructor are injected on **every**
call — your code never hand-builds request bodies or leaks another user's scope.

## Copy-paste snippets

**Govern a memory (legal hold blocks deletion):**

```python
from memoryops import LegalHoldError

mo.set_legal_hold(memory_id, on=True, reason="litigation")
try:
    mo.delete_memory(memory_id)
except LegalHoldError:
    ...  # blocked until the hold is released
mo.set_legal_hold(memory_id, on=False)
mo.delete_memory(memory_id)
```

**Honor consent withdrawal (retention worker will expire it):**

```python
mo.set_consent(memory_id, status="withdrawn")
```

**Preview retention decisions (read-only, deletes nothing):**

```python
for d in mo.retention_decisions(policy="strict"):
    print(d.memory_id, d.outcome, d.eligible_for_deletion, d.blocked_by)
```

**Recall without storing (read-only turn):**

```python
hits = mo.chat("What do you know about me?", temporary_chat=True).used_memories
```

**Read the audit trail (governance evidence):**

```python
for e in mo.audit(limit=20):
    print(e.action, e.reason)
```

## API surface

| Area | Methods |
|---|---|
| Chat | `chat(message, temporary_chat=, conversation_id=)` |
| Memories | `list_memories`, `get_memory`, `update_memory`, `delete_memory`, `memory_audit`, `memory_provenance` |
| Retention / hold / consent | `set_legal_hold`, `pin`, `protect`, `set_consent`, `retention_policies`, `retention_decisions`, `memory_governance` |
| Governance / ops | `audit`, `metrics`, `loops`, `loop_trace`, `health`, `workers_health` |

Errors are typed: `NotFoundError` (404), `LegalHoldError` (409 from a held-memory
delete), and `APIError` (other non-2xx) — all subclasses of `MemoryOpsError`.

## Examples

Runnable scripts in [`examples/`](examples):

- [`quickstart.py`](examples/quickstart.py) — capture → retrieve → govern → forget.
- [`fastapi_integration.py`](examples/fastapi_integration.py) — put governed memory behind your own assistant endpoint.
- [`rag_assistant.py`](examples/rag_assistant.py) — blend governed user memory with your own RAG context.
- [`agent_memory.py`](examples/agent_memory.py) — give a tool-using agent governed, inspectable long-term memory.

## Testing / in-process use

Pass any `httpx.Client` (including FastAPI's `TestClient`) via `http_client=` to
drive the SDK in-process without a network:

```python
from fastapi.testclient import TestClient
from app.main import app
from memoryops import MemoryOpsClient

mo = MemoryOpsClient("http://testserver", "t", "u", http_client=TestClient(app))
```

Run the SDK test suite:

```bash
cd packages/memoryops-sdk && pytest -q
```

See [docs/assistant-sdk.md](../../docs/assistant-sdk.md) for the project-level
overview.
