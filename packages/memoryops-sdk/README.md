# MemoryOps AI — Python SDK (1.0.0)

A small, typed Python client for the [MemoryOps AI](https://github.com/patibandlavenkatamanideep/memoryops-ai)
API. It makes the governed memory lifecycle — capture, retrieve, govern, forget,
audit — a few method calls, while the **server stays the source of truth** for
tenant isolation, policy-before-storage, the deletion guarantee, legal hold,
consent, and audit.

> The SDK is a thin, faithful client over the HTTP API. It adds no governance of
> its own — it just makes the governed API easy to call from assistants, agents,
> and RAG apps.

## 1. Install the SDK

```bash
pip install memoryops-sdk
```

Only dependency: `httpx`. That's all you need to *call* a MemoryOps API — you do
not need to clone the repo.

## 2. Connect to a MemoryOps API

Point the client at any running MemoryOps API and scope it to a tenant/user:

```python
from memoryops import MemoryOpsClient

with MemoryOpsClient("https://your-memoryops-host", "tenant_demo", "user_demo") as mo:
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

The `tenant_id` and `user_id` you pass to the constructor are injected on **every
scope-bearing** call — your code never hand-builds request bodies or leaks another
user's scope. (Global endpoints — `loops`, `loop_trace`, `health`, `workers_health`
— carry no per-tenant scope by design.)

### Authentication

With the default `MEMORYOPS_AUTH_MODE=none`, the API trusts the caller-supplied
scope and no credentials are needed. When it runs with an auth adapter
([auth-adapters.md](https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/docs/auth-adapters.md)),
attach credentials on construction — they are sent on every request:

```python
# Bearer JWT (MEMORYOPS_AUTH_MODE=jwt)
MemoryOpsClient(base_url, tenant_id, user_id, token=my_jwt)

# Trusted upstream header, an API key, or any custom default headers
MemoryOpsClient(base_url, tenant_id, user_id,
                headers={"X-MemoryOps-User": "user_demo"})

# Dynamic / refreshing credentials
MemoryOpsClient(base_url, tenant_id, user_id, auth=my_httpx_auth)
```

The server authorizes independently: credentials must resolve to the same
`tenant_id`/`user_id` scope, or the API returns 401/403.

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
| Construct | `MemoryOpsClient(base_url, tenant_id, user_id, *, token=, headers=, auth=, timeout=, http_client=)` |
| Chat | `chat(message, temporary_chat=, conversation_id=, audience=)` |
| Memories | `list_memories`, `get_memory`, `update_memory`, `delete_memory`, `memory_audit`, `memory_provenance` |
| Retention / hold / consent | `set_legal_hold`, `pin`, `protect`, `set_consent`, `retention_policies`, `retention_decisions`, `memory_governance` |
| Governance / ops | `audit`, `metrics`, `loops`, `loop_trace`, `health`, `workers_health` |

Errors are typed: `NotFoundError` (404), `LegalHoldError` (409 from a held-memory
delete), and `APIError` (other non-2xx) — all subclasses of `MemoryOpsError`.

## Examples

Runnable scripts in the repo under
[`packages/memoryops-sdk/examples/`](https://github.com/patibandlavenkatamanideep/memoryops-ai/tree/main/packages/memoryops-sdk/examples):

- [`quickstart.py`](https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/packages/memoryops-sdk/examples/quickstart.py) — capture → retrieve → govern → forget.
- [`fastapi_integration.py`](https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/packages/memoryops-sdk/examples/fastapi_integration.py) — put governed memory behind your own assistant endpoint.
- [`rag_assistant.py`](https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/packages/memoryops-sdk/examples/rag_assistant.py) — blend governed user memory with your own RAG context.
- [`agent_memory.py`](https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/packages/memoryops-sdk/examples/agent_memory.py) — give a tool-using agent governed, inspectable long-term memory.

## 3. Run the server locally (optional)

You only need this to run your *own* MemoryOps API — SDK users pointing at a hosted
API can skip it. Clone the repo, then start the API with the in-memory backend (no
infrastructure required):

```bash
git clone https://github.com/patibandlavenkatamanideep/memoryops-ai
cd memoryops-ai/services/api
pip install -r requirements.txt
MEMORYOPS_STORAGE=memory uvicorn app.main:app --reload   # serves http://localhost:8000
```

Then point the client at `http://localhost:8000` as in step 2.

## Testing / in-process use

Pass any `httpx.Client` (including FastAPI's `TestClient`) via `http_client=` to
drive the SDK in-process without a network. This requires a repo checkout so the
`app` package is importable (see step 3):

```python
from fastapi.testclient import TestClient
from app.main import app
from memoryops import MemoryOpsClient

mo = MemoryOpsClient("http://testserver", "t", "u", http_client=TestClient(app))
```

Run the SDK test suite (from a repo checkout):

```bash
cd memoryops-ai/packages/memoryops-sdk && pytest -q
```

See [docs/assistant-sdk.md](https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/docs/assistant-sdk.md)
for the project-level overview.
