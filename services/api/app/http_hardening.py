"""Dependency-free request hygiene: body-size cap + in-process rate limiting (P2.4).

The public demo runs as a single instance, so a `while true; curl` loop is a real
denial-of-wallet / abuse vector. This adds two cheap protections, both no-throw
(invariant #4 — a limiter bug must never turn into a 500):

* **Body cap** — reject `/api/*` requests whose `Content-Length` exceeds
  ``max_request_bytes`` with 413 (schema-level ``max_length`` catches the rest).
* **Rate limiting** — a per-IP sliding window over all `/api/*`, with stricter
  windows on `/api/chat` (per tenant/IP) and `/api/evals/*`. Over the limit → 429
  with ``Retry-After``.

In-process state is fine for one instance; put a gateway/Redis limiter in front for
multi-instance. Toggle with ``MEMORYOPS_RATE_LIMIT_ENABLED``.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class SlidingWindowLimiter:
    """A fixed-window-per-key limiter using a monotonic-timestamp deque."""

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds). Records the hit when allowed."""
        if limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - self._window
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry = self._window - (now - dq[0])
                return False, max(1, int(retry) + 1)
            dq.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Process-wide limiter (shared across requests).
_limiter = SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    # Honor a single proxy hop (Railway) via X-Forwarded-For, else the socket peer.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: int, trace_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit exceeded", "trace_id": trace_id},
        headers={"Retry-After": str(retry_after)},
    )


def install_http_hardening(app: FastAPI) -> None:
    @app.middleware("http")
    async def hardening(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        from .core.config import get_settings

        settings = get_settings()
        trace_id = getattr(request.state, "trace_id", "-")

        # 1. Body-size cap (cheap Content-Length check; schema max_length backs it up).
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_request_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "detail": f"request body exceeds {settings.max_request_bytes} bytes",
                    "trace_id": trace_id,
                },
            )

        # 2. Rate limiting (no-throw — never let a limiter bug become a 500).
        if settings.rate_limit_enabled:
            try:
                ip = _client_ip(request)
                ok, retry = _limiter.check(f"ip:{ip}", settings.rate_limit_per_minute)
                if ok and path == "/api/chat":
                    principal = getattr(request.state, "principal", None)
                    key = principal.tenant_id if principal is not None else ip
                    ok, retry = _limiter.check(f"chat:{key}", settings.rate_limit_chat_per_minute)
                if ok and path.startswith("/api/evals"):
                    ok, retry = _limiter.check(f"evals:{ip}", settings.rate_limit_evals_per_minute)
                if not ok:
                    return _too_many(retry, trace_id)
            except Exception:  # noqa: BLE001 — limiter must never break the request
                pass

        return await call_next(request)
