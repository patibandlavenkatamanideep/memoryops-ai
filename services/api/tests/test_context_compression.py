"""Context compression behavior (v0.2.1): noop default, metrics, ordering."""

from __future__ import annotations

from app.compression.headroom_adapter import HeadroomCompressor
from app.compression.noop import NoopCompressor
from app.schemas.memory import ChatRequest


def _chat(gateway, message, **kw):
    return gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message=message, **kw), trace_id="test"
    )


def test_noop_compressor_returns_original_text():
    c = NoopCompressor()
    r = c.compress_context("hello world this is context", trace_id="t")
    assert r.compressed_text == "hello world this is context"
    assert r.provider == "noop"
    assert r.tokens_saved_estimate == 0
    assert r.failed is False


def test_default_gateway_has_no_compression_metadata(gateway):
    # Default config is "none" → transparent noop → no compression block surfaced.
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    resp = _chat(gateway, "Which dashboard theme do I like?")
    assert resp.compression is None


def test_compression_metrics_present(gateway):
    gateway._compressor = HeadroomCompressor(engine=lambda _t: "short")
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    resp = _chat(gateway, "Which dashboard theme do I like?")
    assert resp.compression is not None
    assert resp.compression.enabled is True
    assert resp.compression.provider == "headroom"
    assert resp.compression.original_tokens_estimate >= resp.compression.compressed_tokens_estimate
    assert resp.compression.tokens_saved_estimate >= 0
    assert 0.0 <= resp.compression.compression_ratio <= 1.0


def test_used_memory_ids_survive_compression_metadata(gateway):
    gateway._compressor = HeadroomCompressor(engine=lambda _t: "x")
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    resp = _chat(gateway, "Which dashboard theme do I like?")
    # Compression shrinks the LLM context, not the explainability metadata.
    assert resp.used_memories
    assert all(u.memory_id for u in resp.used_memories)


def test_compression_runs_after_policy_not_before(gateway):
    seen: list[str] = []

    def spy(text: str) -> str:
        seen.append(text)
        return text

    gateway._compressor = HeadroomCompressor(engine=spy)
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    _chat(gateway, "Which dashboard theme do I like?")
    # The compressor only ever sees the governed, composed context block —
    # never the raw user message.
    assert seen
    assert any("dark mode" in s.lower() for s in seen)
    assert all("which dashboard theme do i like" not in s.lower() for s in seen)
