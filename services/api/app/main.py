"""MemoryOps AI API — FastAPI application factory.

Wires middleware (trace_id + structured request log), CORS for the web app, a
catch-all error handler, and the route modules.
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .core.config import get_settings
from .core.logging import clear_request_context, get_logger, set_request_context, setup_logging
from .routes import audit, chat, evals, health, loops, memories

settings = get_settings()
setup_logging(settings.log_level)
logger = get_logger("memoryops.http")

app = FastAPI(
    title="MemoryOps AI API",
    version=__version__,
    description="Enterprise memory governance layer — write path, governance, audit.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten per-environment in production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    set_request_context(trace_id)
    start = time.monotonic()
    try:
        response = await call_next(request)
    finally:
        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            f"{request.method} {request.url.path}",
            extra={"event": "http_request", "latency_ms": latency_ms, "status": "done"},
        )
        clear_request_context()
    response.headers["x-trace-id"] = trace_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    logger.exception("unhandled error", extra={"event": "error", "status": "500"})
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error", "trace_id": getattr(request.state, "trace_id", "-")},
    )


app.include_router(health.router)
app.include_router(chat.router)
app.include_router(memories.router)
app.include_router(audit.router)
app.include_router(evals.router)
app.include_router(loops.router)


@app.get("/")
def root() -> dict:
    return {
        "name": "MemoryOps AI API",
        "version": __version__,
        "docs": "/docs",
        "storage": settings.storage,
    }
