"""Agent memory: give a tool-using agent governed, inspectable long-term memory.

MemoryOps becomes the agent's memory tool. The agent can remember facts across
sessions, recall them, and respect governance (consent withdrawal, legal hold)
without implementing any of that itself. Each tool call is audited server-side.

The "agent" here is a tiny stub loop; wire these tools into your real agent
framework (function/tool calling) as needed.
"""

from __future__ import annotations

from memoryops import MemoryOpsClient

BASE_URL = "http://localhost:8000"


class MemoryTool:
    """A governed memory tool an agent can call."""

    def __init__(self, mo: MemoryOpsClient) -> None:
        self._mo = mo

    def remember(self, fact: str) -> str:
        result = self._mo.chat(f"Remember this: {fact}")
        decided = [c.decision for c in result.candidate_memories]
        return f"stored (decisions={decided})"

    def recall(self, query: str) -> list[str]:
        result = self._mo.chat(query, temporary_chat=True)  # recall without storing
        return [u.content for u in result.used_memories]

    def forget(self, memory_id: str) -> str:
        self._mo.delete_memory(memory_id)
        return "forgotten"

    def withdraw_consent(self, memory_id: str) -> str:
        """Honor a user revoking consent — the retention worker will expire it."""
        self._mo.set_consent(memory_id, status="withdrawn")
        return "consent withdrawn; memory now eligible for retention deletion"


def main() -> None:
    with MemoryOpsClient(BASE_URL, tenant_id="tenant_demo", user_id="agent_demo") as mo:
        tool = MemoryTool(mo)

        # Session 1: the agent learns durable facts.
        print(tool.remember("The user's project is named Atlas."))
        print(tool.remember("The user deploys on Railway."))

        # Session 2 (later): the agent recalls them.
        recalled = tool.recall("What is the user's project and where do they deploy?")
        print("recalled:", recalled)

        # Governance: the user withdraws consent for one memory.
        memories = mo.list_memories()
        if memories:
            print(tool.withdraw_consent(memories[0].id))

        # The agent can inspect its own audit trail (governance evidence).
        print("recent audit:", [e.action for e in mo.audit(limit=5)])


if __name__ == "__main__":
    main()
