"""Cost accounting (§20). Raw token usage is the primary evidence; estimated cost is
derived metadata. Prices come from a dated config and are ``null`` until manually
verified from official provider docs immediately before execution — an unverified
price yields ``None`` cost, never a fabricated number.
"""

from __future__ import annotations

from pathlib import Path


def load_pricing(path: str | Path) -> dict:
    import yaml

    return yaml.safe_load(Path(path).read_text()) or {}


def estimate_cost(pricing: dict, provider: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD estimate, or None if either price is unverified (null)."""
    spec = (pricing.get("providers", {}) or {}).get(provider)
    if not spec:
        return None
    pin = spec.get("input_per_million")
    pout = spec.get("output_per_million")
    if pin is None or pout is None:
        return None  # price not yet verified → no fabricated cost
    return (input_tokens / 1_000_000) * float(pin) + (output_tokens / 1_000_000) * float(pout)
