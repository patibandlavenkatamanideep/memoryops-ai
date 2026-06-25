"""Advisory model price table (USD per 1M tokens).

These are *estimates* for cost instrumentation, not billing. Prices are list
prices for the models the repo names by default; unknown models (including the
deterministic `stub` providers) are **unpriced** — token counts are still tracked
but estimated cost is `$0`. Operators override per-model prices via
`MEMORYOPS_PRICING_OVERRIDES` (JSON); see `docs/economics.md`.

Consistent with ADR-007 / `docs/token-compression.md`: MemoryOps reports
measured/estimated numbers and never asserts a fixed headline cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..core.logging import get_logger

logger = get_logger("memoryops.economics")


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1,000,000 tokens. ``output`` applies to generated tokens;
    ``embedding`` to embedded tokens. Unused fields stay 0.0."""

    input: float = 0.0
    output: float = 0.0
    embedding: float = 0.0


# Default advisory list prices (USD / 1M tokens) for the models referenced in
# core/config.py. Update as providers change pricing; operators can override.
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "text-embedding-3-small": ModelPrice(embedding=0.02),
    "gpt-4o-mini": ModelPrice(input=0.15, output=0.60),
    "claude-haiku-4-5-20251001": ModelPrice(input=1.00, output=5.00),
    "gemini-1.5-flash": ModelPrice(input=0.075, output=0.30),
}


def _parse_overrides(raw: str) -> dict[str, ModelPrice]:
    """Parse the MEMORYOPS_PRICING_OVERRIDES JSON. Malformed input is ignored
    (logged) so a bad env var can never break economics or the chat path."""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        out: dict[str, ModelPrice] = {}
        for model, fields in data.items():
            if isinstance(fields, dict):
                out[str(model)] = ModelPrice(
                    input=float(fields.get("input", 0.0)),
                    output=float(fields.get("output", 0.0)),
                    embedding=float(fields.get("embedding", 0.0)),
                )
        return out
    except Exception:  # noqa: BLE001 — advisory config; never fatal
        logger.debug("invalid MEMORYOPS_PRICING_OVERRIDES; ignoring", extra={"event": "economics"})
        return {}


def price_per_1m(model: str, *, overrides_json: str = "") -> ModelPrice | None:
    """Resolve the price for ``model``; returns None when unpriced (e.g. stub).

    Operator overrides take precedence over the default table.
    """
    if not model:
        return None
    overrides = _parse_overrides(overrides_json)
    if model in overrides:
        return overrides[model]
    return DEFAULT_PRICES.get(model)
