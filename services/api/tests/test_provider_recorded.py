"""Recorded real-provider extraction tests (P1.1).

These prove the headline capability — extraction with a *real* model, including
multi-memory turns the deterministic stub can't produce — without needing API keys in
CI. Responses are recorded once (VCR.py via pytest-recording) with the auth header
scrubbed, committed under ``tests/cassettes/``, and replayed deterministically.

Record locally (one time), then commit the cassette:

    OPENAI_API_KEY=sk-... pytest tests/test_provider_recorded.py --record-mode=once

With no cassette and no key (the default CI state) the tests SKIP, so the suite stays
green and offline. See tests/cassettes/README.md.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_CASSETTES = Path(__file__).parent / "cassettes"


def _has_cassette(name: str) -> bool:
    return (_CASSETTES / f"{name}.yaml").exists()


def _extract(provider_name: str, message: str):
    from app.core.config import Settings
    from app.llm import extract_memories
    from app.llm.registry import build_llm_provider

    settings = Settings(llm_provider=provider_name)
    provider = build_llm_provider(settings)
    return extract_memories(provider, message, settings=settings)


@pytest.mark.vcr(filter_headers=["authorization", "x-api-key", "api-key"])
@pytest.mark.skipif(
    not _has_cassette("test_extraction_real_openai_multi") and not os.getenv("OPENAI_API_KEY"),
    reason="no cassette and no OPENAI_API_KEY — record with --record-mode=once",
)
def test_extraction_real_openai_multi():
    out = _extract("openai", "I'm vegetarian and my sister Mia is allergic to peanuts.")
    contents = " ".join(m.content.lower() for m in out.memories)
    # Multi-memory — the stub can never deterministically split these two facts as a
    # real model does; this is the capability the stub can't cover.
    assert len(out.memories) >= 2
    assert "vegetarian" in contents


@pytest.mark.vcr(filter_headers=["authorization", "x-api-key", "api-key"])
@pytest.mark.skipif(
    not _has_cassette("test_extraction_real_anthropic_multi") and not os.getenv("ANTHROPIC_API_KEY"),
    reason="no cassette and no ANTHROPIC_API_KEY — record with --record-mode=once",
)
def test_extraction_real_anthropic_multi():
    out = _extract("anthropic", "Remember I live in Boston, I'm allergic to shellfish, and my anniversary is May 3.")
    contents = " ".join(m.content.lower() for m in out.memories)
    assert len(out.memories) >= 2
    assert "boston" in contents
