"""Headroom fallback behavior (v0.2.1): never block, always degrade safely."""

from __future__ import annotations

from app.compression.headroom_adapter import HeadroomCompressor
from app.schemas.memory import ChatRequest


def _chat(gateway, message, **kw):
    return gateway.handle_chat(
        ChatRequest(tenant_id="t1", user_id="u1", message=message, **kw), trace_id="test"
    )


def test_headroom_missing_falls_back_to_noop():
    # No engine injected and headroom-ai not installed → import fails → safe result.
    c = HeadroomCompressor()
    r = c.compress_context("some governed context block", trace_id="t")
    assert r.failed is True
    assert r.compressed_text == "some governed context block"  # original preserved
    assert r.provider == "headroom"
    assert r.reason and "unavailable" in r.reason


def test_headroom_runtime_error_falls_back():
    def boom(_text: str) -> str:
        raise RuntimeError("compress boom")

    c = HeadroomCompressor(engine=boom)
    r = c.compress_context("governed context", trace_id="t")
    assert r.failed is True
    assert r.compressed_text == "governed context"


def test_compression_failure_does_not_block_chat(gateway):
    def boom(_text: str) -> str:
        raise RuntimeError("compress boom")

    gateway._compressor = HeadroomCompressor(engine=boom)
    _chat(gateway, "Remember that I prefer dark mode dashboards.")
    resp = _chat(gateway, "Which dashboard theme do I like?")
    # Chat still answered; compression reported as fallback.
    assert resp.assistant_message
    assert resp.compression is not None
    assert resp.compression.enabled is True
    assert resp.compression.fallback is True
