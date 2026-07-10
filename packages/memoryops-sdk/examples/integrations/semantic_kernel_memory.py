"""Semantic Kernel + MemoryOps — a governed memory plugin.

Semantic Kernel exposes capabilities as plugins (native functions). This wraps
MemoryOps remember/recall as SK-style native functions so a kernel's planner/agent can
use governed long-term memory as a first-class skill.

Run: pip install semantic-kernel ; and have a MemoryOps API reachable. Illustrative.
"""

from __future__ import annotations

from memoryops import GovernedMemory, MemoryOpsClient


class MemoryOpsPlugin:
    """A Semantic Kernel plugin exposing governed memory as native functions.

    With SK installed you would decorate these with `@kernel_function`; the bodies are
    unchanged, so the plugin works with or without the decorator.
    """

    def __init__(self, memory: GovernedMemory) -> None:
        self._memory = memory

    def remember(self, fact: str) -> str:
        """Persist a durable fact through governed memory."""
        return f"stored={self._memory.remember(fact).stored}"

    def recall(self, query: str) -> str:
        """Recall relevant governed memory for a query."""
        return "\n".join(self._memory.recall(query))


def build(base_url: str = "http://localhost:8000") -> MemoryOpsPlugin:
    client = MemoryOpsClient(base_url, tenant_id="tenant_demo", user_id="user_demo")
    return MemoryOpsPlugin(GovernedMemory(client))


# Sketch:
#   import semantic_kernel as sk
#   kernel = sk.Kernel()
#   kernel.add_plugin(build(), plugin_name="memory")
#   # The kernel/planner can now call memory.remember / memory.recall as skills.
if __name__ == "__main__":
    plugin = build()
    print(plugin.remember("The user leads the platform team."))
    print(plugin.recall("what team does the user lead?"))
