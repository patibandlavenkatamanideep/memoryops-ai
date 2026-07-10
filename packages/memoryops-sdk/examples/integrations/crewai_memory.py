"""CrewAI + MemoryOps — governed shared memory for a crew of agents.

CrewAI agents share memory across tasks. Backing that with MemoryOps means every agent
in the crew reads/writes through one governed, audited, tenant-scoped memory — and you
can hand different agents different `audience` clearances (e.g. a customer-facing agent
gets `public`, an internal analyst gets `private`).

Run: pip install crewai ; and have a MemoryOps API reachable. Illustrative.
"""

from __future__ import annotations

from memoryops import GovernedMemory, MemoryOpsClient


def crew_memory(audience: str = "private", base_url: str = "http://localhost:8000") -> GovernedMemory:
    client = MemoryOpsClient(base_url, tenant_id="tenant_demo", user_id="user_demo")
    return GovernedMemory(client, audience=audience)


def as_crewai_tools(memory: GovernedMemory) -> list[dict]:
    """Expose remember/recall as CrewAI-style tool specs (name + callable)."""
    return [
        {"name": "remember", "description": "Persist a durable fact (governed).",
         "func": lambda fact: memory.remember(fact).decisions},
        {"name": "recall", "description": "Recall relevant governed memory.",
         "func": memory.recall},
    ]


# Sketch:
#   from crewai import Agent
#   internal = crew_memory("private")     # full clearance
#   facing = crew_memory("public")        # low-sensitivity memory only
#   analyst = Agent(role="Analyst", tools=as_crewai_tools(internal), ...)
#   support = Agent(role="Support",  tools=as_crewai_tools(facing),  ...)
#   # Same governed store; the Recall Gate keeps sensitive memory out of the
#   # customer-facing agent's context automatically.
if __name__ == "__main__":
    internal = crew_memory("private")
    internal.remember("Internal margin target is 42 percent.")
    print("internal:", internal.recall("what is our margin target?"))
    print("public:", crew_memory("public").recall("what is our margin target?"))
