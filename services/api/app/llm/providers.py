"""Shared base for networked LLM providers (v0.4).

Concrete providers (OpenAI/Anthropic/Gemini) implement ``_invoke`` to call their
SDK; this base wraps every call with retry-with-backoff and turns any SDK error
into an ``LLMUnavailableError`` so the structured-intelligence orchestrator falls
back to the deterministic heuristic instead of crashing the chat path
(invariant #4). SDKs are imported lazily inside ``_invoke`` so the package
imports cleanly without them installed.

Retries are **classified**: only failures that could succeed on an identical retry
are tried again (see ``app.llm.errors``). A deterministic rejection — a bad
request, a bad key, an unknown local error — fails after a single attempt and
degrades to the heuristic immediately, instead of spending the full retry budget
to arrive at the same result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.logging import get_logger
from ..core.reliability import with_retry
from .base import LLMUnavailableError
from .errors import is_retryable_provider_error, status_code_of

logger = get_logger("memoryops.llm")


class BaseNetworkProvider(ABC):
    """Common retry/error-handling envelope for networked providers."""

    name = "network"

    def __init__(self, *, api_key: str, model: str, timeout: float, max_retries: int) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        # ``with_retry`` counts total attempts; max_retries is *additional* tries.
        self._attempts = max(1, max_retries + 1)

    def complete(self, *, system: str, user: str, task: str = "general") -> str:
        if not self._api_key:
            raise LLMUnavailableError(f"{self.name}: no API key configured")

        def _call() -> str:
            return self._invoke(system=system, user=user, task=task)

        try:
            return with_retry(
                _call, attempts=self._attempts, retry_if=is_retryable_provider_error
            )
        except Exception as exc:  # noqa: BLE001 — normalize to a fallback signal
            logger.warning(
                "llm provider call failed",
                extra={
                    "event": "llm_provider_failure",
                    "provider": self.name,
                    "task": task,
                    # Content-free: whether the failure was worth retrying, and the
                    # status class if the SDK reported one. Never the request, the
                    # prompt, the response body, or the key.
                    "retryable": is_retryable_provider_error(exc),
                    "status": status_code_of(exc),
                },
            )
            raise LLMUnavailableError(f"{self.name} call failed: {exc}") from exc

    @abstractmethod
    def _invoke(self, *, system: str, user: str, task: str) -> str:  # pragma: no cover
        """Call the provider SDK and return raw completion text."""
        raise NotImplementedError
