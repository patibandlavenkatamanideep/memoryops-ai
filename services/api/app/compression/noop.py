"""No-op compressor — the default, fully transparent path (v0.2.1).

Returns the original context unchanged (zero tokens saved). Keeping a real
compressor in the default path means the gateway always calls the same
interface; turning compression on is a config change, not a code path change.
"""

from __future__ import annotations

from .base import CompressionResult
from .metrics import build_result


class NoopCompressor:
    provider = "noop"

    def compress_context(self, text: str, *, trace_id: str) -> CompressionResult:
        return build_result(self.provider, text, text)
