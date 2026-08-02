"""Embedding provider tests (v0.3): determinism, dimension, fallback target."""

from __future__ import annotations

from app.embeddings import cosine, embed, get_embedding_provider
from app.embeddings.stub import StubEmbeddingProvider


def test_stub_embedding_is_deterministic():
    a = embed("I prefer enterprise-style architecture explanations.")
    b = embed("I prefer enterprise-style architecture explanations.")
    assert a == b


def test_stub_embedding_has_configured_dimension():
    provider = get_embedding_provider()
    vec = embed("hello world")
    assert len(vec) == provider.dim == 1536


def test_stub_embedding_is_l2_normalized():
    vec = StubEmbeddingProvider(1536).embed_text("dark mode dashboards")
    norm = sum(v * v for v in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_default_provider_is_stub_offline():
    # No API key configured in tests → deterministic stub, never a network call.
    assert get_embedding_provider().name == "stub"


def test_embed_batch_matches_single():
    texts = ["alpha beta", "gamma delta"]
    batch = StubEmbeddingProvider(64).embed_batch(texts)
    assert batch == [StubEmbeddingProvider(64).embed_text(t) for t in texts]


def test_related_text_more_similar_than_unrelated():
    base = embed("I prefer dark mode dashboards")
    related = embed("dark mode dashboards are my preference")
    unrelated = embed("the capital of France is Paris")
    assert cosine(base, related) > cosine(base, unrelated)


# ── embedding-space integrity ────────────────────────────────────────────────
# A failed network provider must never substitute a stub vector. The stub lives in
# a *different* embedding space but is indistinguishable from a real vector once
# persisted, so a transient outage used to permanently poison the index with
# meaningless distances. Full coverage in tests/test_embedding_integrity.py.
def test_failed_provider_raises_rather_than_returning_a_stub_vector():
    import pytest

    from app.embeddings.providers import EmbeddingUnavailable, OpenAIEmbeddingProvider

    class _Down(OpenAIEmbeddingProvider):
        def _client(self):
            raise RuntimeError("provider unreachable")

    provider = _Down(api_key="sk-test", model="text-embedding-3-small", dim=64)
    with pytest.raises(EmbeddingUnavailable):
        provider.embed_text("dark mode dashboards")


def test_openai_selection_without_a_key_still_degrades_to_stub_offline():
    # Selection-time fallback is retained so the app always starts in dev; it is the
    # *call-time* fallback that fabricated cross-space vectors. Production rejects
    # this combination at startup (Settings.production_readiness_errors).
    from app.embeddings.providers import build_provider

    assert build_provider().name == "stub"
