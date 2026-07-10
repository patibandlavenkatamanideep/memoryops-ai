"""GovernedMemory — a framework-agnostic memory adapter (v2.1).

Every agent framework (LangGraph, LlamaIndex, CrewAI, AutoGen, Semantic Kernel, the
OpenAI Agents SDK) has *some* memory interface: write a fact, read relevant context,
forget. `GovernedMemory` is the thin, uniform adapter every framework example wraps —
so the governance (policy-before-storage, admission, recall/output gates, deletion
guarantees, audit) lives once, on the server, and each integration is just glue.

The server stays authoritative: this adds no governance, it only routes an agent's
memory calls through the governed pipeline via `MemoryOpsClient`.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import MemoryOpsClient


@dataclass
class RememberResult:
    stored: bool
    decisions: list[str]
    memory_ids: list[str]


class GovernedMemory:
    """A minimal remember / recall / forget surface over the governed API.

    `audience` (``private`` | ``team`` | ``public``) is applied to every recall so a
    lower-trust session never sees higher-sensitivity memory (Recall Gate, v1.9).
    """

    def __init__(self, client: MemoryOpsClient, *, audience: str = "private") -> None:
        self._mo = client
        self._audience = audience

    # ── write ────────────────────────────────────────────────────────────────
    def remember(self, fact: str) -> RememberResult:
        """Route a fact through policy-before-storage; the broker decides if it's kept."""
        result = self._mo.chat(f"Remember this: {fact}")
        decisions = [c.decision for c in result.candidate_memories]
        ids = [c.memory_id for c in result.candidate_memories if getattr(c, "memory_id", None)]
        stored = any(d in ("SAVE", "UPDATE_EXISTING", "MERGE_WITH_EXISTING") for d in decisions)
        return RememberResult(stored=stored, decisions=decisions, memory_ids=ids)

    # ── read ─────────────────────────────────────────────────────────────────
    def recall(self, query: str) -> list[str]:
        """Return the memory contents admitted into context for `query` (audience-gated)."""
        result = self._mo.chat(query, audience=self._audience)
        return [u.content for u in result.used_memories]

    def context_for(self, query: str, *, header: str = "Relevant memory:") -> str:
        """A ready-to-inject context block for an agent prompt (empty string if none)."""
        recalled = self.recall(query)
        if not recalled:
            return ""
        return header + "\n" + "\n".join(f"- {c}" for c in recalled)

    def answer(self, query: str) -> str:
        """Let MemoryOps compose the governed answer directly (memory-augmented reply)."""
        return self._mo.chat(query, audience=self._audience).assistant_message

    # ── forget ───────────────────────────────────────────────────────────────
    def forget(self, memory_id: str) -> None:
        """Delete a memory — the deletion guarantee (#2) and audit apply server-side."""
        self._mo.delete_memory(memory_id)

    def withdraw_consent(self, memory_id: str) -> None:
        """Honor a user revoking consent; the memory is then gated out + retention-eligible."""
        self._mo.set_consent(memory_id, status="withdrawn")

    def for_audience(self, audience: str) -> "GovernedMemory":
        """A view of the same memory for a different audience/clearance."""
        return GovernedMemory(self._mo, audience=audience)
