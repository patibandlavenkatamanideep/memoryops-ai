"""AutoGen + MemoryOps — governed memory tools for a conversable agent.

AutoGen agents call registered functions/tools. Register MemoryOps remember/recall as
tools and the agent gets governed long-term memory: policy-before-storage on writes,
admission/recall gates on reads, deletion + audit for free.

Run: pip install pyautogen ; and have a MemoryOps API reachable. Illustrative.
"""

from __future__ import annotations

from memoryops import GovernedMemory, MemoryOpsClient


def memory_functions(base_url: str = "http://localhost:8000") -> dict:
    client = MemoryOpsClient(base_url, tenant_id="tenant_demo", user_id="user_demo")
    memory = GovernedMemory(client)

    def remember(fact: str) -> str:
        """Persist a durable fact through governed memory."""
        return f"stored={memory.remember(fact).stored}"

    def recall(query: str) -> str:
        """Recall relevant governed memory for a query."""
        return "\n".join(memory.recall(query)) or "(no relevant memory)"

    return {"remember": remember, "recall": recall}


# Sketch:
#   from autogen import AssistantAgent, UserProxyAgent
#   fns = memory_functions()
#   assistant = AssistantAgent("assistant", llm_config={...})
#   user = UserProxyAgent("user", function_map=fns)   # exposes remember/recall
#   # In the assistant's system message, instruct it to call `recall` before
#   # answering and `remember` after learning a durable fact.
if __name__ == "__main__":
    fns = memory_functions()
    print(fns["remember"]("The user's timezone is IST."))
    print(fns["recall"]("what timezone is the user in?"))
