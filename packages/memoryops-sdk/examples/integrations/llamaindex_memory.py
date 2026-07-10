"""LlamaIndex + MemoryOps — governed chat memory for a LlamaIndex agent/chat engine.

LlamaIndex has a memory abstraction (e.g. `ChatMemoryBuffer`) that feeds prior context
into the LLM. Wrap MemoryOps as that memory so long-term recall is governed: admitted
memory respects consent, retention, deletion, and audience clearance.

Run: pip install llama-index ; and have a MemoryOps API reachable. Illustrative.
"""

from __future__ import annotations

from memoryops import GovernedMemory, MemoryOpsClient


class MemoryOpsChatMemory:
    """A minimal LlamaIndex-style memory backed by governed MemoryOps recall.

    Mirrors the parts a LlamaIndex chat engine needs: `put` a message, `get` the
    relevant context string for the next LLM call.
    """

    def __init__(self, memory: GovernedMemory) -> None:
        self._memory = memory

    def put(self, role: str, content: str) -> None:
        # Persist durable user facts; the policy broker drops trivia/secrets.
        if role == "user":
            self._memory.remember(content)

    def get(self, query: str) -> str:
        return self._memory.context_for(query, header="Context from memory:")


def build(base_url: str = "http://localhost:8000") -> MemoryOpsChatMemory:
    client = MemoryOpsClient(base_url, tenant_id="tenant_demo", user_id="user_demo")
    return MemoryOpsChatMemory(GovernedMemory(client))


# Sketch:
#   from llama_index.core.chat_engine import SimpleChatEngine
#   mem = build()
#   mem.put("user", "I'm allergic to penicillin.")
#   context = mem.get("what medications should I avoid?")
#   # pass `context` as system context to your LlamaIndex chat engine / query engine.
if __name__ == "__main__":
    m = build()
    m.put("user", "I'm allergic to penicillin.")
    print(m.get("what medications should I avoid?"))
