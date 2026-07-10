"""Structured JSON logging with secret redaction and request trace context.

Patterned after hermes-agent's centralized logging: a single ``setup_logging``
entry point and a ``RedactingFormatter`` so secrets are never written to disk or
stdout. A contextvar carries ``trace_id`` so every log line for a request can be
correlated (ADR-004).
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar

from .redaction import redact_secrets

_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="-")
_user_id: ContextVar[str] = ContextVar("user_id", default="-")


def set_request_context(trace_id: str, tenant_id: str = "-", user_id: str = "-") -> None:
    _trace_id.set(trace_id)
    _tenant_id.set(tenant_id)
    _user_id.set(user_id)


def clear_request_context() -> None:
    _trace_id.set("-")
    _tenant_id.set("-")
    _user_id.set("-")


class RedactingJsonFormatter(logging.Formatter):
    """Emits one JSON object per line, with secrets redacted from the message."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": _trace_id.get(),
            "tenant_id": _tenant_id.get(),
            "user_id": _user_id.get(),
            "message": redact_secrets(record.getMessage()),
        }
        # v1.8: correlate each log line with the active tracing span (ADR-022).
        try:
            from ..observability.tracing import current_span_id

            if (span_id := current_span_id()) is not None:
                payload["span_id"] = span_id
        except Exception:  # noqa: BLE001 - logging must never fail on tracing
            pass
        # Attach structured extras passed via logger.info(..., extra={"event": ...}).
        # v0.4 adds LLM-layer fields (provider/task/fallback/candidate/conflict
        # counts) so structured-intelligence events are observable (ADR-008).
        for key in (
            "event", "latency_ms", "memory_count", "status", "decision",
            "provider", "task", "fallback", "candidate_count", "conflict_count", "schema",
        ):
            if (value := getattr(record, key, None)) is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact_secrets(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    # Replace handlers so re-init (tests, reload) doesn't duplicate output.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(RedactingJsonFormatter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
