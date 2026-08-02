"""Embedding-space integrity: a failed provider must never fabricate a vector.

The OpenAI embedding adapter used to catch provider errors and return
``StubEmbeddingProvider`` output in their place. That reads like graceful
degradation (invariant #4) but is a silent correctness bug: the stub vector lives
in a *different embedding space* from the model's, yet is indistinguishable from a
real one once persisted. A transient outage permanently poisoned the index with
vectors whose distances are meaningless, with no signal and no way to identify the
affected rows later.

Invariant #4 requires that a failure never *blocks the response*; it does not
license fabricating data. The correct degradation is no vector at all — callers
already treat an empty embedding as keyword-only ranking.
"""

from __future__ import annotations

import pytest

from app.embeddings.providers import (
    EmbeddingUnavailable,
    OpenAIEmbeddingProvider,
    build_provider,
)
from app.embeddings.stub import StubEmbeddingProvider


class _BoomProvider(OpenAIEmbeddingProvider):
    """OpenAI adapter whose underlying client always fails."""

    def _client(self):
        raise RuntimeError("provider unreachable")


def test_failed_embedding_raises_instead_of_returning_a_stub_vector():
    provider = _BoomProvider(api_key="sk-test", model="text-embedding-3-small", dim=64)
    with pytest.raises(EmbeddingUnavailable):
        provider.embed_text("I prefer dark mode dashboards")


def test_failed_batch_embedding_raises_instead_of_returning_stub_vectors():
    provider = _BoomProvider(api_key="sk-test", model="text-embedding-3-small", dim=64)
    with pytest.raises(EmbeddingUnavailable):
        provider.embed_batch(["alpha", "beta"])


def test_failure_never_yields_a_vector_from_the_stub_space():
    """The regression itself: no code path may return the stub's vector for this text.

    Asserted on the value, not just the exception type, so a future "helpful"
    fallback re-introduced anywhere in the adapter still fails this test.
    """
    text = "quarterly revenue was discussed in the board meeting"
    provider = _BoomProvider(api_key="sk-test", model="text-embedding-3-small", dim=64)
    stub_vector = StubEmbeddingProvider(64).embed_text(text)

    try:
        result = provider.embed_text(text)
    except EmbeddingUnavailable:
        return  # correct behaviour
    assert result != stub_vector, (
        "a failed OpenAI embedding returned a stub vector — cross-space contamination"
    )


def test_write_path_degrades_to_no_vector_not_a_fake_one(monkeypatch):
    """`safe_call` in write_service turns the raise into an empty embedding.

    Empty means keyword-only ranking for that memory: recoverable and re-embeddable,
    unlike a persisted vector in the wrong space.
    """
    from app.core.reliability import safe_call

    provider = _BoomProvider(api_key="sk-test", model="text-embedding-3-small", dim=64)
    embedding = safe_call(lambda: provider.embed_text("hello"), default=[], label="embed")
    assert embedding == []


def test_retriever_degrades_to_keyword_only_when_embedding_fails(monkeypatch):
    """Invariant #4 still holds: retrieval falls back rather than raising."""
    from app.db.factory import get_repository
    from app.services import retriever as retriever_module

    def _boom(_text):
        raise EmbeddingUnavailable("provider unreachable")

    monkeypatch.setattr(retriever_module, "embed", _boom)
    result = retriever_module.Retriever(get_repository()).retrieve("t1", "u1", "any query")
    assert result.mode == "fallback"


def test_offline_selection_still_returns_the_stub_provider():
    """Removing the runtime fallback must not make the offline default networked."""
    assert build_provider().name == "stub"
