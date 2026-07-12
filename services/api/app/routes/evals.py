"""Eval endpoints.

`POST /api/evals/run` executes the full eval harness on demand. That is real
compute, so exposing it unauthenticated on a public deployment is a denial-of-wallet
vector. It is therefore OFF by default (`MEMORYOPS_PUBLIC_EVALS=false`) and returns
403 unless an operator opts in.

`GET /api/evals/latest` serves a server-cached result (regenerated at most once per
`evals_cache_ttl_seconds`) so a playground/dashboard can always show eval results
without letting anyone trigger unbounded on-demand runs.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, HTTPException

from ..core.config import get_settings
from ..services.eval_harness import run_evals

router = APIRouter(prefix="/api/evals", tags=["evaluation"])

# Process-wide cache for GET /latest so a public reader can never trigger more than
# one harness run per TTL window regardless of request volume.
_cache_lock = threading.Lock()
_cached: dict | None = None
_cached_at: float = 0.0


def _latest_cached() -> dict:
    global _cached, _cached_at
    ttl = get_settings().evals_cache_ttl_seconds
    now = time.monotonic()
    with _cache_lock:
        if _cached is None or (now - _cached_at) >= ttl:
            _cached = run_evals().to_dict()
            _cached_at = now
        return _cached


@router.post("/run")
def run() -> dict:
    """Trigger a fresh eval-harness run. Guarded — off by default."""
    if not get_settings().public_evals:
        raise HTTPException(
            status_code=403,
            detail=(
                "on-demand eval runs are disabled; set MEMORYOPS_PUBLIC_EVALS=true to "
                "enable, or use GET /api/evals/latest for cached results"
            ),
        )
    return run_evals().to_dict()


@router.get("/latest")
def latest() -> dict:
    """Return the most recent eval result, regenerating at most once per TTL."""
    return _latest_cached()
