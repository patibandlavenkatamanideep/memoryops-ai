"""Dependency-free tracing façade with an optional OpenTelemetry bridge (v1.8, ADR-022).

Every memory-lifecycle stage — write, retrieve, rank, admission, compose, worker jobs,
deletion-proof checks — opens a `span` under a request/job **correlation id**. Spans are:

- **Content-free + low-cardinality.** Attributes are counts, modes, decisions, phase
  names — never memory content, message text, or raw tenant/user ids. Safe to expose.
- **No-throw.** Recording never raises (invariant #4); a span records `error` status on
  an exception and re-raises the original.
- **Zero new dependency by default.** Spans land in a bounded in-process ring buffer
  (the `GET /api/traces` view + dashboard). If the OpenTelemetry SDK is installed *and*
  `otel_enabled`, the same spans are also emitted to your real tracing backend.

The correlation id is the request `trace_id` (set by the HTTP middleware) or a fresh id
for background jobs, so a chat turn or a worker run is one correlated trace end-to-end.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock

_MAX_SPANS = 512
_recent: deque[dict] = deque(maxlen=_MAX_SPANS)
_lock = Lock()

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
_current_span: ContextVar[str | None] = ContextVar("current_span", default=None)

# Resolved once from settings; None means "recording on, OTel off".
_otel_tracer = None
_otel_checked = False


@dataclass
class Span:
    name: str
    correlation_id: str
    span_id: str
    parent_span_id: str | None
    start: float
    attributes: dict = field(default_factory=dict)
    status: str = "ok"
    duration_ms: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "correlation_id": self.correlation_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
        }


def set_correlation_id(correlation_id: str) -> None:
    _correlation_id.set(correlation_id or "-")


def new_correlation_id(prefix: str = "job") -> str:
    """Mint + set a correlation id for a background job (workers have no HTTP trace)."""
    cid = f"{prefix}-{uuid.uuid4().hex[:16]}"
    set_correlation_id(cid)
    return cid


def current_correlation_id() -> str:
    return _correlation_id.get()


def current_span_id() -> str | None:
    return _current_span.get()


def _resolve_otel():
    """Lazily wire an OTel tracer iff the SDK is present and enabled. Never raises."""
    global _otel_tracer, _otel_checked
    if _otel_checked:
        return _otel_tracer
    _otel_checked = True
    try:
        from ..core.config import get_settings

        if not get_settings().otel_enabled:
            return None
        from opentelemetry import trace  # type: ignore

        _otel_tracer = trace.get_tracer("memoryops")
    except Exception:  # noqa: BLE001 - OTel is fully optional
        _otel_tracer = None
    return _otel_tracer


def _record(span: Span) -> None:
    with _lock:
        _recent.append(span.to_dict())


@contextmanager
def span(name: str, **attributes):
    """Open a span under the current correlation id; record duration + status on exit."""
    try:
        from ..core.config import get_settings

        if not get_settings().tracing_enabled:
            yield None
            return
    except Exception:  # noqa: BLE001 - never let tracing config break a request
        yield None
        return

    parent = _current_span.get()
    sp = Span(
        name=name,
        correlation_id=_correlation_id.get(),
        span_id=uuid.uuid4().hex[:16],
        parent_span_id=parent,
        start=time.monotonic(),
        attributes={k: v for k, v in attributes.items() if v is not None},
    )
    token = _current_span.set(sp.span_id)
    otel = _resolve_otel()
    otel_cm = otel.start_as_current_span(name) if otel is not None else None
    if otel_cm is not None:
        otel_span = otel_cm.__enter__()
        with contextlib_suppress():
            for k, v in sp.attributes.items():
                otel_span.set_attribute(f"memoryops.{k}", v)
    try:
        yield sp
    except Exception:
        sp.status = "error"
        raise
    finally:
        sp.duration_ms = int((time.monotonic() - sp.start) * 1000)
        _record(sp)
        _current_span.reset(token)
        if otel_cm is not None:
            with contextlib_suppress():
                otel_cm.__exit__(None, None, None)


@contextmanager
def contextlib_suppress():
    try:
        yield
    except Exception:  # noqa: BLE001
        pass


def recent_spans(limit: int = 100, *, correlation_id: str | None = None) -> list[dict]:
    """Most-recent spans (newest first), optionally filtered to one correlated trace."""
    with _lock:
        items = list(_recent)
    if correlation_id:
        items = [s for s in items if s["correlation_id"] == correlation_id]
    return list(reversed(items))[:limit]


def reset_spans() -> None:
    """Test hook — clear the ring buffer."""
    with _lock:
        _recent.clear()
