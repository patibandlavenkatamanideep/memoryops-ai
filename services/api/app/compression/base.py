"""Context compression interface (v0.2.1).

A `ContextCompressor` shrinks the *composed context block* (already-governed,
already-retrieved memories) right before it is handed to the LLM — never before
the policy broker, and never the raw user message. See ADR-007.

Synchronous on purpose: the MemoryOps read path (retriever → ranker → composer →
gateway → LLM) is synchronous end-to-end, so the compression boundary stays sync
to read like the surrounding code and avoid a broad async rewrite (consistent
with the embedding provider interface in ADR-006).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class CompressionResult(BaseModel):
    """Outcome of a single context-compression attempt.

    On failure, ``compressed_text`` is the original text so callers can use it
    unchanged (compression must never block a chat — invariant: graceful
    degradation).
    """

    original_text: str
    compressed_text: str
    original_tokens_estimate: int
    compressed_tokens_estimate: int
    tokens_saved_estimate: int
    compression_ratio: float = Field(
        ..., description="fraction of input tokens saved: tokens_saved / original"
    )
    provider: str
    failed: bool = False
    reason: str | None = None


@runtime_checkable
class ContextCompressor(Protocol):
    def compress_context(self, text: str, *, trace_id: str) -> CompressionResult:
        ...
