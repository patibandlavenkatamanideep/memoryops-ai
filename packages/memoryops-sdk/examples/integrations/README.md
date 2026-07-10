# Agent framework integrations

MemoryOps plugs into real agent systems as the **governed memory layer**. Every
framework has some notion of memory (write a fact, read relevant context, forget);
these examples wrap one small, uniform adapter — `memoryops.GovernedMemory` — so the
governance lives once, on the server, and each integration is just glue.

```python
from memoryops import MemoryOpsClient, GovernedMemory

mo = MemoryOpsClient("http://localhost:8000", "tenant_demo", "user_demo")
memory = GovernedMemory(mo, audience="private")

memory.remember("The user prefers metric units.")     # policy-before-storage
memory.recall("what units should I use?")              # admission + recall gated
memory.context_for("...")                              # ready-to-inject prompt block
memory.forget(memory_id)                               # deletion guarantee + audit
```

Because the server is authoritative, every framework below inherits **tenant
isolation, policy-before-storage, the admission + recall/output gates, deletion
guarantees, and the tamper-evident audit trail** without implementing any of it.

| Framework | File | Integration point |
| --- | --- | --- |
| LangGraph | [`langgraph_memory.py`](langgraph_memory.py) | recall/remember graph nodes over long-term memory |
| LlamaIndex | [`llamaindex_memory.py`](llamaindex_memory.py) | a governed chat-memory (`put`/`get`) |
| CrewAI | [`crewai_memory.py`](crewai_memory.py) | shared crew memory + per-agent `audience` clearance |
| AutoGen | [`autogen_memory.py`](autogen_memory.py) | remember/recall registered as agent functions |
| Semantic Kernel | [`semantic_kernel_memory.py`](semantic_kernel_memory.py) | a memory plugin (native functions) |
| OpenAI Agents SDK | [`openai_agents_memory.py`](openai_agents_memory.py) | remember/recall as function tools |

## Notes

- Each example is **illustrative** and import-guarded: the framework package is
  optional, and the file runs a tiny self-contained demo under `__main__` against a
  reachable MemoryOps API (`MEMORYOPS_STORAGE=memory uvicorn app.main:app`).
- `audience` (`private`/`team`/`public`) applies the [Recall Gate](../../../../docs/recall-output-gates.md):
  give a customer-facing agent `public` and an internal agent `private`, backed by the
  same governed store.
- The adapter adds **no** governance — the server stays the source of truth. See
  [docs/agent-integrations.md](../../../../docs/agent-integrations.md).
