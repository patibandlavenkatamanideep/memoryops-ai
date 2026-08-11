"""Fallback behavior: provider failure / invalid JSON degrade to the heuristic,
and an LLM can never override the deterministic policy broker."""

from __future__ import annotations

from app.core.config import Settings
from app.db.memory_repo import InMemoryRepository
from app.llm import extract_memories
from app.llm.base import LLMUnavailableError
from app.llm.providers import BaseNetworkProvider
from app.schemas.memory import ChatRequest, Decision, Source
from app.services.extractor import Extractor
from app.services.gateway import Gateway

from ._secret_fixtures import FAKE_PROVIDER_KEY


class _RaisingProvider:
    name = "raising"

    def complete(self, *, system: str, user: str, task: str = "general") -> str:
        raise LLMUnavailableError("simulated provider failure")


class _GarbageProvider:
    name = "garbage"

    def complete(self, *, system: str, user: str, task: str = "general") -> str:
        return "I am not JSON, I am free text the model rambled."


class _SecretInjectingProvider:
    """A hostile/buggy provider that tries to push a secret into a memory."""

    name = "hostile"

    def complete(self, *, system: str, user: str, task: str = "general") -> str:
        return (
            '{"memories": [{"content": "API key is ' + FAKE_PROVIDER_KEY + '",'
            ' "type": "semantic", "importance": 9, "confidence": 0.99}]}'
        )


def test_provider_failure_falls_back_to_heuristic() -> None:
    outcome = extract_memories(_RaisingProvider(), "Remember that I prefer dark mode.")
    assert outcome.mode == "heuristic"
    assert len(outcome.memories) == 1
    assert "dark mode" in outcome.memories[0].content.lower()


def test_invalid_json_falls_back_to_heuristic() -> None:
    outcome = extract_memories(_GarbageProvider(), "Remember that I prefer concise answers.")
    assert outcome.mode == "heuristic"
    assert len(outcome.memories) == 1


def test_failed_provider_never_blocks_chat() -> None:
    repo = InMemoryRepository()
    gw = Gateway(repo)
    gw._extractor = Extractor(provider=_RaisingProvider())
    resp = gw.handle_chat(
        ChatRequest(tenant_id="t", user_id="u", message="Remember I prefer dark mode."),
        trace_id="test",
    )
    # Response is produced and the heuristic-extracted memory is saved.
    assert resp.assistant_message
    assert any(c.decision == Decision.SAVE for c in resp.candidate_memories)


def test_llm_cannot_override_policy_secret_block() -> None:
    # Even when the provider returns a high-importance memory carrying a secret,
    # the deterministic policy broker blocks it (LLM is advisory only, ADR-008).
    ex = Extractor(provider=_SecretInjectingProvider())
    repo = InMemoryRepository()
    gw = Gateway(repo)
    gw._extractor = ex
    resp = gw.handle_chat(
        ChatRequest(tenant_id="t", user_id="u", message="store my key please"),
        trace_id="test",
    )
    decisions = [c.decision for c in resp.candidate_memories]
    assert Decision.BLOCK in decisions
    assert Decision.SAVE not in decisions
    # Nothing secret-bearing was stored.
    stored = repo.list_memories("t", "u", include_deleted=True)
    assert all("sk-test" not in s.content for s in stored if s.status.value == "active")


def test_strict_mode_disables_heuristic_rescue() -> None:
    outcome = extract_memories(
        _RaisingProvider(),
        "Remember I prefer dark mode.",
        settings=Settings(llm_fallback_to_heuristic=False),
    )
    assert outcome.mode == "strict_empty"
    assert outcome.memories == []


def test_extractor_keeps_provenance_on_fallback() -> None:
    ex = Extractor(provider=_RaisingProvider())
    src = Source(kind="chat", excerpt="orig")
    cands = ex.extract("Remember I prefer dark mode.", src)
    assert cands and cands[0].source.excerpt == "orig"


# ── retry classification does not change what the orchestrator sees ──────────
class _CountingNetworkProvider(BaseNetworkProvider):
    """A real networked provider whose SDK call always fails with a scripted error.

    Uses `BaseNetworkProvider` rather than a hand-rolled double so the retry
    envelope under test is the one production actually runs.
    """

    name = "counting"

    def __init__(self, error: Exception) -> None:
        super().__init__(
            api_key="unit" + "-test-" + "placeholder",
            model="m",
            timeout=1.0,
            max_retries=2,
        )
        self._error = error
        self.calls = 0

    def _invoke(self, *, system: str, user: str, task: str) -> str:
        self.calls += 1
        raise self._error


class _PermanentError(Exception):
    """Provider-SDK shape for a deterministic rejection (HTTP 400)."""

    status_code = 400


class _TransientError(Exception):
    """Provider-SDK shape for a retryable fault (HTTP 503)."""

    status_code = 503


def test_a_permanent_provider_failure_falls_back_after_a_single_attempt() -> None:
    """Fail-fast changes the cost of the failure, not the outcome.

    The heuristic still answers, exactly as it does for a transient outage — but a
    deterministic rejection no longer spends the whole retry budget first.
    """
    provider = _CountingNetworkProvider(_PermanentError())
    outcome = extract_memories(provider, "Remember that I prefer dark mode.")
    assert outcome.mode == "heuristic"
    assert "dark mode" in outcome.memories[0].content.lower()
    assert provider.calls == 1


def test_a_transient_provider_failure_still_uses_the_full_retry_budget() -> None:
    provider = _CountingNetworkProvider(_TransientError())
    outcome = extract_memories(provider, "Remember that I prefer dark mode.")
    assert outcome.mode == "heuristic"
    assert provider.calls == 3


def test_a_permanent_provider_failure_never_blocks_chat() -> None:
    """Invariant #4 end to end, with the fail-fast path in the chat request."""
    repo = InMemoryRepository()
    provider = _CountingNetworkProvider(_PermanentError())
    gw = Gateway(repo)
    gw._extractor = Extractor(provider=provider)
    resp = gw.handle_chat(
        ChatRequest(tenant_id="t", user_id="u", message="Remember I prefer dark mode."),
        trace_id="test",
    )
    assert resp.assistant_message
    assert any(c.decision == Decision.SAVE for c in resp.candidate_memories)
    assert provider.calls == 1
