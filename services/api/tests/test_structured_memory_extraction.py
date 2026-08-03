"""Structured extraction orchestration: stub path is structured + deterministic."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.llm import StubProvider, extract_memories
from app.schemas.memory import MemoryType, Source
from app.services.extractor import Extractor


def test_stub_extraction_is_structured_mode() -> None:
    outcome = extract_memories(StubProvider(), "Remember that I prefer concise answers.")
    assert outcome.mode == "structured"
    assert outcome.provider == "stub"
    assert len(outcome.memories) == 1
    assert outcome.memories[0].type == MemoryType.preference


def test_extractor_maps_to_candidate_with_provenance() -> None:
    ex = Extractor(provider=StubProvider())
    src = Source(kind="chat", excerpt="orig message")
    candidates = ex.extract("I'm building MemoryOps AI for a hackathon.", src)
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand.type == MemoryType.project
    assert cand.source.excerpt == "orig message"  # invariant #3: provenance preserved


def test_extractor_emits_no_candidate_for_question() -> None:
    ex = Extractor(provider=StubProvider())
    assert ex.extract("What editor should I use?", Source()) == []


def test_strict_mode_without_fallback_extracts_nothing_on_bad_provider() -> None:
    # A provider that always raises + fallback disabled → safe empty (never blocks).
    class _Broken:
        name = "broken"

        def complete(self, *, system: str, user: str, task: str = "general") -> str:
            raise RuntimeError("boom")

    settings = Settings(llm_fallback_to_heuristic=False)
    outcome = extract_memories(_Broken(), "Remember that I prefer dark mode.", settings=settings)
    assert outcome.mode == "strict_empty"
    assert outcome.memories == []


# ── memory-control instructions produce no candidate ─────────────────────────
# "do not remember my password" is an instruction *about* memory, not a fact. The
# extractor declines it before the provider is consulted, so no candidate exists to
# be blocked later — storing the sentence as a high-sensitivity record would be the
# same disclosure by another route. The policy broker repeats the check
# independently (tests/test_sensitivity_classification.py), so an LLM extractor that
# emits a candidate anyway still cannot store it.
@pytest.mark.parametrize(
    "message",
    [
        "do not remember my password",
        "never save my password",
        "forget my salary",
        "do not store my medical information",
        "I don't want you to remember my address",
    ],
)
def test_extractor_emits_no_candidate_for_a_memory_control_instruction(message):
    from app.services.extractor import Extractor

    candidates = Extractor().extract(message, Source(kind="chat", excerpt=message))
    assert candidates == [], f"a candidate was extracted from: {message}"


def test_extractor_still_extracts_ordinary_facts():
    """The guard must not suppress normal extraction."""
    from app.services.extractor import Extractor

    msg = "Remember: I prefer dark mode dashboards."
    assert Extractor().extract(msg, Source(kind="chat", excerpt=msg)), (
        "the memory-control guard suppressed a legitimate fact"
    )


def test_a_sensitive_disclosure_is_still_extracted_then_governed():
    """Detection belongs to the broker, not the extractor.

    The extractor must not silently drop sensitive content — that would hide it
    from governance. It extracts, and the broker blocks or gates.
    """
    from app.services.extractor import Extractor

    msg = "Remember: my HIV status is positive."
    assert Extractor().extract(msg, Source(kind="chat", excerpt=msg))
