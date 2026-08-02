"""Extractor — turns a conversation turn into candidate memories.

As of v0.4 the extractor delegates to the provider-neutral LLM layer
(``app/llm``) for structured extraction, then maps the validated
``ExtractedMemory`` objects onto ``CandidateMemory`` with provenance attached
(invariant #3). The default provider is the deterministic ``StubProvider``, which
expresses the original heuristic, so behavior is unchanged with no API keys and
no network — and the policy broker still runs after this and stays authoritative
(LLM output is advisory only, ADR-008).
"""

from __future__ import annotations

from ..core.sensitivity import is_memory_control_instruction
from ..llm import get_llm_provider
from ..llm.base import LLMProvider
from ..llm.intelligence import extract_memories
from ..schemas.memory import CandidateMemory, Source


class Extractor:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        # Provider is injectable for tests; defaults to the cached, settings-
        # selected provider (stub unless a real key is configured).
        self._provider = provider or get_llm_provider()

    def extract(self, message: str, source: Source) -> list[CandidateMemory]:
        text = message.strip()
        if not text:
            return []

        # "do not remember my password" is an instruction *about* memory, not a fact
        # to store. Emitting a candidate for it and then blocking would be the wrong
        # shape: the correct outcome is that no memory is ever created, and storing
        # the sentence as a high-sensitivity record would be the same disclosure by
        # another route. The policy broker repeats this check independently, so an
        # LLM extractor that emits a candidate anyway still cannot store it.
        if is_memory_control_instruction(text):
            return []

        outcome = extract_memories(self._provider, text)
        # Map validated model output onto candidates; the policy broker assigns
        # the final sensitivity and the storage decision.
        return [
            CandidateMemory(
                content=mem.content,
                type=mem.type,
                confidence=mem.confidence,
                importance=mem.importance,
                sensitivity=mem.sensitivity,
                source=source,
            )
            for mem in outcome.memories
        ]
