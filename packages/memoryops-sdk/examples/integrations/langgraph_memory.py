"""LangGraph + MemoryOps — governed long-term memory for a graph agent.

LangGraph gives you short-term state (the graph's channels) and a place to persist
long-term memory. Point that long-term memory at MemoryOps so every write goes through
policy-before-storage and every read through the admission/recall gates — the graph
never implements governance itself.

Run: pip install langgraph langchain-core ; and have a MemoryOps API reachable.
This file is illustrative — the LangGraph import is optional.
"""

from __future__ import annotations

from memoryops import GovernedMemory, MemoryOpsClient


def build_memory(base_url: str = "http://localhost:8000") -> GovernedMemory:
    client = MemoryOpsClient(base_url, tenant_id="tenant_demo", user_id="user_demo")
    return GovernedMemory(client, audience="private")


def recall_node(state: dict, memory: GovernedMemory) -> dict:
    """A graph node: enrich state with governed memory context before the LLM node."""
    query = state["messages"][-1]["content"]
    state["memory_context"] = memory.context_for(query)
    return state


def remember_node(state: dict, memory: GovernedMemory) -> dict:
    """A graph node: persist durable facts from the turn (the broker decides)."""
    for fact in state.get("facts_to_remember", []):
        memory.remember(fact)
    return state


# Wiring sketch (pseudocode — see the LangGraph docs for StateGraph specifics):
#
#   from langgraph.graph import StateGraph
#   memory = build_memory()
#   g = StateGraph(dict)
#   g.add_node("recall", lambda s: recall_node(s, memory))
#   g.add_node("agent", your_llm_node)          # reads state["memory_context"]
#   g.add_node("remember", lambda s: remember_node(s, memory))
#   g.add_edge("recall", "agent"); g.add_edge("agent", "remember")
#   g.set_entry_point("recall")
#
# The store is authoritative for governance; the graph just calls remember/recall.
if __name__ == "__main__":
    mem = build_memory()
    mem.remember("The user prefers metric units.")
    print("context:", mem.context_for("what units should I use?"))
