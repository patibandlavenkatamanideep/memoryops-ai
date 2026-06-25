"""Advisory economics: per-request token + cost estimation (v1.2, ADR-016).

Builds on the deterministic token estimator (`compression.metrics.estimate_tokens`)
and a configurable advisory price table. Costs are *estimates* for instrumentation,
never billing; unknown/stub models are unpriced ($0). Surfaced per-request on the
chat response and as content-free Prometheus counters on `GET /metrics`.
"""

from .estimator import RequestEconomics, build_request_economics, estimate_cost_usd
from .pricing import DEFAULT_PRICES, ModelPrice, price_per_1m

__all__ = [
    "RequestEconomics",
    "build_request_economics",
    "estimate_cost_usd",
    "price_per_1m",
    "ModelPrice",
    "DEFAULT_PRICES",
]
