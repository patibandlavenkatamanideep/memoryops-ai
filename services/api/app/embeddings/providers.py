"""Optional network embedding providers + provider selection.

Rules:
  * Tests and offline runs never require a real key — selection falls back to the
    deterministic stub whenever a provider is unconfigured (dev profile only).
  * A configured provider that raises at call time raises ``EmbeddingUnavailable``
    rather than substituting a stub vector.

Why a failed embedding must NOT become a stub vector
----------------------------------------------------
This module used to catch provider errors and return ``StubEmbeddingProvider``
output in their place. That looks like graceful degradation (invariant #4) but it
is a correctness bug: the stub vector is a *different embedding space* from the
model's, yet it is indistinguishable from a real one once persisted. A transient
OpenAI outage therefore permanently poisoned the index with vectors whose cosine
distance to real ones is meaningless — silently degrading retrieval quality with
no signal, and no way to find the affected rows afterwards.

Invariant #4 says a retrieval failure must never *block the response*; it does not
say a failure may fabricate data. The correct degradation is **no vector**: callers
(`write_service`, `retriever`) already wrap embedding in `safe_call(..., default=[])`,
and an empty embedding degrades that memory to keyword-only ranking — recoverable,
observable, and re-embeddable later. See docs/embedding-integrity.md.
"""

from __future__ import annotations

from ..core.config import get_settings
from ..core.logging import get_logger
from .stub import StubEmbeddingProvider

logger = get_logger("memoryops.embeddings")


class EmbeddingUnavailable(RuntimeError):
    """The configured embedding provider could not produce a vector.

    Raised instead of returning a stub vector from a different embedding space.
    Callers degrade to keyword-only ranking (empty embedding) rather than
    persisting a fabricated vector.
    """


class OpenAIEmbeddingProvider:
    """OpenAI embeddings, used only when ``OPENAI_API_KEY`` is set.

    Imports the ``openai`` SDK lazily so the package imports cleanly without it.
    Pads/truncates to ``dim`` so the stored vector always matches the column
    dimension regardless of model.
    """

    name = "openai"

    def __init__(self, api_key: str, model: str, dim: int = 1536) -> None:
        self._api_key = api_key
        self._model = model
        self.dim = dim

    def _client(self):  # pragma: no cover - needs the openai package + key
        from openai import OpenAI

        return OpenAI(api_key=self._api_key)

    def _fit(self, vec: list[float]) -> list[float]:
        if len(vec) == self.dim:
            return vec
        if len(vec) > self.dim:
            return vec[: self.dim]
        return vec + [0.0] * (self.dim - len(vec))

    def _fail(self, exc: Exception, op: str) -> EmbeddingUnavailable:
        # Content-free log: provider/model/op only, never the embedded text.
        logger.warning(
            "openai embedding failed; degrading to no vector (keyword-only)",
            extra={
                "event": "embed_unavailable",
                "provider": self.name,
                "model": self._model,
                "op": op,
                "error": type(exc).__name__,
            },
        )
        return EmbeddingUnavailable(f"{self.name}/{self._model} {op} failed: {type(exc).__name__}")

    def embed_text(self, text: str) -> list[float]:
        try:  # pragma: no cover - exercised only with a real key
            resp = self._client().embeddings.create(model=self._model, input=text)
            return self._fit(list(resp.data[0].embedding))
        except Exception as exc:  # noqa: BLE001 — never fabricate a cross-space vector
            raise self._fail(exc, "embed_text") from exc

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:  # pragma: no cover - exercised only with a real key
            resp = self._client().embeddings.create(model=self._model, input=texts)
            return [self._fit(list(d.embedding)) for d in resp.data]
        except Exception as exc:  # noqa: BLE001
            raise self._fail(exc, "embed_batch") from exc


def build_provider():
    """Select an embedding provider from settings, defaulting to the stub.

    ``MEMORYOPS_EMBEDDING_PROVIDER`` / ``embeddings_provider`` accepts
    ``stub`` (alias ``heuristic``) or ``openai``.

    ``openai`` without a key falls back to the stub so the app always starts in the
    dev profile. Under ``MEMORYOPS_PROFILE=production`` that combination is rejected
    at startup by ``Settings.production_readiness_errors`` — a production deployment
    that asked for real embeddings must not quietly serve stub ones.
    """
    settings = get_settings()
    dim = settings.embedding_dim
    provider = settings.embeddings_provider
    if provider == "openai" and settings.openai_api_key:
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
            dim=dim,
        )
    if provider == "openai":
        logger.warning(
            "embedding provider 'openai' selected without an API key; using stub",
            extra={"event": "embed_provider_fallback", "provider": "stub", "fallback": True},
        )
    return StubEmbeddingProvider(dim)
