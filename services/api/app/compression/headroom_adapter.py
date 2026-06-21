"""Optional Headroom-backed context compressor (v0.2.1).

Headroom (https://github.com/chopratejas/headroom, Apache-2.0) is an AI context
compression layer. This adapter is **optional**: the package is imported lazily,
and any failure — not installed, unavailable, or a runtime error — degrades to
returning the original text marked ``failed=True`` so the gateway can fall back
to the uncompressed context. Compression must never block a chat.

Headroom is invoked only at the context/LLM boundary, after MemoryOps has run
policy checks, retrieval, governance filtering, and context composition. It never
sees raw, ungoverned content (ADR-007).
"""

from __future__ import annotations

from collections.abc import Callable

from .base import CompressionResult
from .metrics import build_result


class HeadroomCompressor:
    provider = "headroom"

    def __init__(
        self,
        engine: Callable[[str], str] | None = None,
        *,
        mode: str = "library",
        output_shaper: bool = False,
    ) -> None:
        # `engine` is injectable so tests never need a real Headroom install.
        self._engine = engine
        self._mode = mode
        self._output_shaper = output_shaper

    def _load_engine(self) -> Callable[[str], str]:
        if self._engine is not None:
            return self._engine
        # Lazy import: the app must run without headroom-ai installed.
        from headroom import compress  # type: ignore  # pragma: no cover - needs package

        self._engine = compress
        return self._engine

    def compress_context(self, text: str, *, trace_id: str) -> CompressionResult:
        if not text:
            return build_result(self.provider, text, text)
        try:
            engine = self._load_engine()
        except Exception as exc:  # noqa: BLE001 — optional dependency / unavailable
            return build_result(
                self.provider, text, text,
                failed=True, reason=f"headroom unavailable: {type(exc).__name__}",
            )
        try:
            compressed = engine(text)
            if not isinstance(compressed, str):
                compressed = str(compressed)
        except Exception as exc:  # noqa: BLE001 — runtime failure → safe fallback
            return build_result(
                self.provider, text, text, failed=True, reason=str(exc)
            )
        return build_result(self.provider, text, compressed)
