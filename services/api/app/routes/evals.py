"""Eval endpoints.

`POST /api/evals/run` executes the full eval harness. That is real compute, so
exposing it unauthenticated on a public deployment is a denial-of-wallet vector. It
is OFF by default (`MEMORYOPS_PUBLIC_EVALS=false`) and returns 403 unless an operator
opts in.

`GET /api/evals/latest` is a **pure read** of the last completed run.

Why that distinction is load-bearing
------------------------------------
`latest` used to regenerate whenever the process cache was cold or older than
`evals_cache_ttl_seconds`, so holding `evals:read` granted bounded but real
*execution* authority — collapsing the very split `evals:read` / `evals:run` exists to
make. A TTL limits how often the work happens; it does not turn the action into a
read. Nothing on the GET path calls the harness now, and `run` is the only request
path that does.

The result is **process-wide and has no tenant dimension**: these are deployment-level
evaluation results (the harness runs against its own isolated fixtures, not tenant
data), which is why the route takes no tenant parameter — and why both endpoints are
`ops:*` rather than tenant capabilities. A tenant administrator running the harness
would spend platform compute and replace the result every other tenant reads; that is
platform operation, not tenant administration.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from ..auth import Permission, require_permission
from ..core.config import get_settings
from ..services.eval_harness import run_evals

router = APIRouter(prefix="/api/evals", tags=["evaluation"])

# The last completed run, deployment-wide. Written only by `POST /run`.
_cache_lock = threading.Lock()
_cached: dict | None = None
_cached_at: float = 0.0


def _store_result(result: dict) -> dict:
    """Replace the last-completed result. Called only after a successful run."""
    global _cached, _cached_at
    stamped = {**result, "generated_at": datetime.now(UTC).isoformat()}
    with _cache_lock:
        _cached = stamped
        _cached_at = time.monotonic()
        return _cached


def _latest_completed() -> dict | None:
    """The last completed result, or None if this process has never finished one.

    Deliberately never regenerates. An old result is still the latest *completed*
    result, and serving it is honest; recomputing here would hand execution authority
    to every reader.
    """
    with _cache_lock:
        return _cached


def reset_cache() -> None:
    """Test hook — forget the last completed run."""
    global _cached, _cached_at
    with _cache_lock:
        _cached = None
        _cached_at = 0.0


@router.post("/run")
def run(request: Request) -> dict:
    """Trigger a fresh eval-harness run. Guarded — off by default.

    Also refreshes what `GET /latest` serves, so the only path that spends the compute
    is the only path that updates the result.
    """
    require_permission(request, Permission.OPS_EVALS_RUN)
    if not get_settings().public_evals:
        raise HTTPException(
            status_code=403,
            detail=(
                "on-demand eval runs are disabled; set MEMORYOPS_PUBLIC_EVALS=true to "
                "enable, or use GET /api/evals/latest for the last completed result"
            ),
        )
    return _store_result(run_evals().to_dict())


@router.get("/latest")
def latest(request: Request) -> dict:
    """The last completed eval run. Never triggers one.

    `ops:evals:read`. Deployment-level evidence, so a tenant auditor does not hold it:
    the result describes this installation, not their tenant.

    404 when this process has completed no run: there is no result to report, and
    manufacturing one would be exactly the execution path this route must not have.
    """
    require_permission(request, Permission.OPS_EVALS_READ)
    result = _latest_completed()
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "no_result_available: no evaluation has completed in this process; "
                "trigger one with POST /api/evals/run"
            ),
        )
    return result
