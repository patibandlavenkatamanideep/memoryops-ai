"""Context compression package (v0.2.1).

Optional, non-invasive token compression at the context/LLM boundary. The default
is the transparent `NoopCompressor`; `HeadroomCompressor` activates only when
``MEMORYOPS_CONTEXT_COMPRESSION=headroom`` and degrades to no-op on any failure.
See ADR-007 and docs/integrations/headroom.md.
"""

from __future__ import annotations

from functools import lru_cache

from ..core.config import get_settings
from .base import CompressionResult, ContextCompressor
from .headroom_adapter import HeadroomCompressor
from .metrics import build_result, estimate_tokens
from .noop import NoopCompressor

__all__ = [
    "CompressionResult",
    "ContextCompressor",
    "HeadroomCompressor",
    "NoopCompressor",
    "build_result",
    "estimate_tokens",
    "get_compressor",
]


@lru_cache
def get_compressor() -> ContextCompressor:
    settings = get_settings()
    if settings.context_compression == "headroom":
        return HeadroomCompressor(
            mode=settings.headroom_mode,
            output_shaper=settings.headroom_output_shaper,
        )
    return NoopCompressor()
