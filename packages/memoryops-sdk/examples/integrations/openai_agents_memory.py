"""OpenAI Agents SDK + MemoryOps — governed memory as function tools.

The OpenAI Agents SDK lets an agent call typed function tools. Expose MemoryOps
remember/recall as tools and the agent gains governed long-term memory across runs —
the governance (policy, admission, deletion, audit) is enforced server-side.

Run: pip install openai-agents ; and have a MemoryOps API reachable. Illustrative.
"""

from __future__ import annotations

from memoryops import GovernedMemory, MemoryOpsClient

_client = MemoryOpsClient("http://localhost:8000", tenant_id="tenant_demo", user_id="user_demo")
_memory = GovernedMemory(_client)


def remember_memory(fact: str) -> str:
    """Persist a durable fact about the user through governed memory."""
    return f"stored={_memory.remember(fact).stored}"


def recall_memory(query: str) -> str:
    """Recall relevant governed memory for a query (audience-gated)."""
    return "\n".join(_memory.recall(query)) or "(no relevant memory)"


# Sketch:
#   from agents import Agent, function_tool, Runner
#   remember = function_tool(remember_memory)
#   recall = function_tool(recall_memory)
#   agent = Agent(
#       name="Assistant",
#       instructions="Call recall_memory before answering; call remember_memory "
#                     "after learning a durable fact about the user.",
#       tools=[remember, recall],
#   )
#   Runner.run_sync(agent, "Remember I prefer window seats. Where should I sit?")
if __name__ == "__main__":
    print(remember_memory("The user prefers window seats."))
    print(recall_memory("what seat does the user prefer?"))
