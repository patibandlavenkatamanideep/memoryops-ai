# Agent framework integrations

MemoryOps is the **governed memory layer** for agent systems. Rather than a bespoke SDK
per framework, v2.1 ships one small, uniform adapter — `memoryops.GovernedMemory` — plus
copy-paste examples that wrap it for each framework. The governance lives once, on the
server; each integration is glue.

## The adapter

```python
from memoryops import MemoryOpsClient, GovernedMemory

mo = MemoryOpsClient("http://localhost:8000", "tenant_demo", "user_demo")
memory = GovernedMemory(mo, audience="private")

memory.remember("The user prefers metric units.")   # → policy-before-storage
memory.recall("what units should I use?")            # → admission + recall gated, audited
memory.context_for("...")                            # → ready-to-inject prompt block
memory.answer("...")                                 # → let MemoryOps compose the reply
memory.forget(memory_id)                             # → deletion guarantee + audit
memory.for_audience("public")                        # → a lower-clearance view
```

Because the server is authoritative, every framework inherits **tenant isolation,
policy-before-storage, the admission + recall/output gates, deletion guarantees, and the
tamper-evident audit trail** — the adapter adds no governance of its own.

## Supported frameworks

Runnable examples live in
[`packages/memoryops-sdk/examples/integrations/`](../packages/memoryops-sdk/examples/integrations/):

| Framework | Integration point |
| --- | --- |
| **LangGraph** | recall/remember graph nodes over long-term memory |
| **LlamaIndex** | a governed chat-memory (`put` / `get`) |
| **CrewAI** | shared crew memory + per-agent `audience` clearance |
| **AutoGen** | remember/recall registered as agent functions |
| **Semantic Kernel** | a memory plugin (native functions) |
| **OpenAI Agents SDK** | remember/recall as function tools |

Each example is illustrative and import-guarded (the framework package is optional) and
runs a tiny self-contained demo against a reachable MemoryOps API.

## Per-audience agents

`audience` (`private` / `team` / `public`) applies the
[Recall Gate](recall-output-gates.md). A common pattern is one governed store with
different clearances per agent:

```python
internal = GovernedMemory(mo, audience="private")   # full clearance
facing   = GovernedMemory(mo, audience="public")    # low-sensitivity memory only
```

The customer-facing agent literally cannot recall higher-sensitivity memory — the server
gates it out, not the agent code.

## Why route memory through MemoryOps

- **One governance surface** for a whole crew/graph — not re-implemented per agent.
- **Auditable + verifiable**: every memory op is audited and covered by the v2.0
  tamper-evident chain; hand a reviewer a deletion proof or evidence bundle.
- **Portable**: swap the vector backend (v1.7) or identity provider (v1.6) without
  touching agent code.

The adapter is tested against the real in-process app
(`packages/memoryops-sdk/tests/test_integrations.py`), so the glue is proven to route
through the governed pipeline, not a mock.
