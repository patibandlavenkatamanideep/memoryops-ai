# Tutorial: governed long-term memory for a LangGraph agent

LangGraph gives an agent short-term state (the graph's channels). This tutorial adds
**governed long-term memory** by pointing that memory at MemoryOps — so every write
goes through policy-before-storage and every read through the admission/recall gates,
and you get a verifiable deletion proof for free. The graph never implements governance
itself.

## What you'll build

```
user message ─▶ recall (governed) ─▶ agent (LLM) ─▶ remember (governed) ─▶ reply
```

## 1. Prerequisites

```bash
pip install langgraph langchain-core
pip install -e packages/memoryops-sdk            # the MemoryOps SDK

# Run a MemoryOps API in another terminal (no infra, no keys):
cd services/api && MEMORYOPS_STORAGE=memory uvicorn app.main:app
```

## 2. Wrap MemoryOps as the graph's memory

The SDK ships a framework-agnostic adapter — `GovernedMemory` — with
`remember` / `recall` / `context_for` / `forget`:

```python
from memoryops import MemoryOpsClient, GovernedMemory

client = MemoryOpsClient("http://localhost:8000", tenant_id="tenant_demo", user_id="user_demo")
memory = GovernedMemory(client, audience="private")
```

`audience` applies the Recall Gate: use `"public"` for a customer-facing graph so
higher-sensitivity memory is kept out of context automatically.

## 3. Recall and remember nodes

```python
from typing import TypedDict

class State(TypedDict):
    message: str
    memory_context: str
    reply: str

def recall_node(state: State) -> State:
    # Enrich state with governed memory *before* the LLM node.
    state["memory_context"] = memory.context_for(state["message"])
    return state

def agent_node(state: State) -> State:
    # Your LLM call. The governed context is available as state["memory_context"].
    system = state["memory_context"] or "(no relevant memory)"
    state["reply"] = call_your_llm(system=system, user=state["message"])  # your code
    return state

def remember_node(state: State) -> State:
    # Persist durable facts; the policy broker decides what is actually kept.
    memory.remember(state["message"])
    return state
```

## 4. Build the graph

```python
from langgraph.graph import StateGraph, END

g = StateGraph(State)
g.add_node("recall", recall_node)
g.add_node("agent", agent_node)
g.add_node("remember", remember_node)
g.set_entry_point("recall")
g.add_edge("recall", "agent")
g.add_edge("agent", "remember")
g.add_edge("remember", END)
app = g.compile()

app.invoke({"message": "Remember I prefer metric units. What units should I use?"})
```

The first turn stores the preference (through policy-before-storage); a later turn
recalls it into context — governed, audience-scoped, and audited.

> A runnable skeleton (no LLM required) lives at
> [`packages/memoryops-sdk/examples/integrations/langgraph_memory.py`](../../packages/memoryops-sdk/examples/integrations/langgraph_memory.py).

## 5. Prove governance (the part other memory layers can't)

Because the writes were governed and audited, you can prove what happened:

```python
import httpx
q = {"tenant_id": "tenant_demo", "user_id": "user_demo"}

# What memory the agent actually used / was blocked — on any chat response:
resp = client.chat("what units do I prefer?", audience="private")
print(resp.trace.memories_used, resp.trace.memories_blocked)

# Forget a memory and get a verifiable deletion proof:
mem = client.list_memories()[0]
client.delete_memory(mem.id)
proof = httpx.get("http://localhost:8000/api/evidence/deletion/" + mem.id, params=q).json()
print("deletion proven:", proof["proven"])

# The whole audit trail is tamper-evident:
print("audit intact:", httpx.get("http://localhost:8000/api/evidence/audit/verify", params=q).json()["ok"])
```

## Where to go next

- Give different nodes/agents different `audience` clearances (see the
  [CrewAI example](../../packages/memoryops-sdk/examples/integrations/crewai_memory.py)).
- Swap the vector backend (Qdrant/LanceDB/Weaviate) without touching graph code —
  [adapter matrix](../adapters/README.md).
- Put MemoryOps behind real identity — [auth adapters](../auth-adapters.md).
