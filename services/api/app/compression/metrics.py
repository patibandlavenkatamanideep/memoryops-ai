"""Token estimation + CompressionResult construction (v0.2.1).

Token counts are deterministic *estimates* (≈4 chars/token), not a provider
tokenizer — enough for cost instrumentation and tests without adding a tokenizer
dependency. MemoryOps reports *measured/estimated* savings; it does not claim a
fixed headline number (see docs/token-compression.md).
"""

from __future__ import annotations

from .base import CompressionResult

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def build_result(
    provider: str,
    original_text: str,
    compressed_text: str,
    *,
    failed: bool = False,
    reason: str | None = None,
) -> CompressionResult:
    original = estimate_tokens(original_text)
    compressed = estimate_tokens(compressed_text)
    saved = max(0, original - compressed)
    ratio = round(saved / original, 4) if original else 0.0
    return CompressionResult(
        original_text=original_text,
        compressed_text=compressed_text,
        original_tokens_estimate=original,
        compressed_tokens_estimate=compressed,
        tokens_saved_estimate=saved,
        compression_ratio=ratio,
        provider=provider,
        failed=failed,
        reason=reason,
    )
