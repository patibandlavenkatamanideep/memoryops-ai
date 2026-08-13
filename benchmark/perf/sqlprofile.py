"""Benchmark-only SQL statement profiling (Phase C).

Counts what a request actually asks the database to do — statement count, normalized
query shapes, per-shape time — by attaching to SQLAlchemy's cursor-execute events.

Why this exists
---------------
A CPU profile of the request path showed ~282 `psycopg` `connection.wait` calls per
request. That is a driver-level count, not a statement count, and the two are easy to
conflate: a wait is not a round trip and a round trip is not a statement. Answering
"how chatty is the request path, really?" needs the statements themselves, which is
what this module records.

Not production instrumentation
------------------------------
This is a benchmark tool. It attaches to an engine you hand it, adds a small constant
cost per statement, and is never imported by `services/api`.

Content safety
--------------
Bound parameters are **never** captured — only the statement text, and only after
normalization. `normalize()` strips quoted strings, numbers and placeholders before
anything is stored, so tenant ids, user ids, memory content, embedding vectors and
credentials cannot reach a recorded shape or a serialized artifact. Vector literals
are collapsed first, so a 1536-element embedding becomes one `'<vector>'` token
rather than 1536 separate ones.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter, defaultdict

#: Applied in order. Vector/array literals go first: collapsing them afterwards would
#: leave the numeric scrubber to expand one embedding into a thousand tokens.
_SCRUBBERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"'\[[^\]]*\]'"), "'<vector>'"),
    (re.compile(r"\[[-0-9.eE,\s]{40,}\]"), "<vector>"),
    (re.compile(r"'[^']*'"), "?"),
    (re.compile(r"\b\d+\.\d+\b"), "?"),
    (re.compile(r"\b\d+\b"), "?"),
    (re.compile(r"\$\d+"), "?"),
    (re.compile(r"%\(\w+\)s"), "?"),
    (re.compile(r"%s"), "?"),
    (re.compile(r"\s+"), " "),
)

#: Shapes are truncated so a very long projection list cannot dominate an artifact.
MAX_SHAPE_CHARS = 180


def normalize(sql: str) -> str:
    """Reduce a statement to a parameter-free shape safe to record and group by."""
    text = sql or ""
    for pattern, replacement in _SCRUBBERS:
        text = pattern.sub(replacement, text)
    return text.strip()[:MAX_SHAPE_CHARS]


class SqlProfile:
    """Accumulates statement counts, shapes and timings. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.statements = 0
        self.total_ms = 0.0
        self.by_shape: Counter[str] = Counter()
        self.ms_by_shape: defaultdict[str, float] = defaultdict(float)

    def record(self, sql: str, elapsed_ms: float) -> None:
        shape = normalize(sql)
        with self._lock:
            self.statements += 1
            self.total_ms += elapsed_ms
            self.by_shape[shape] += 1
            self.ms_by_shape[shape] += elapsed_ms

    def reset(self) -> None:
        with self._lock:
            self.statements = 0
            self.total_ms = 0.0
            self.by_shape.clear()
            self.ms_by_shape.clear()

    def top_shapes(self, limit: int = 15) -> list[dict]:
        with self._lock:
            items = sorted(self.by_shape.items(), key=lambda kv: -kv[1])[:limit]
            return [
                {"count": n, "total_ms": round(self.ms_by_shape[s], 3), "shape": s}
                for s, n in items
            ]

    def as_dict(self, *, requests: int = 1, top: int = 15) -> dict:
        """Serializable summary. ``requests`` divides the totals into per-request
        figures, which is the unit the evidence is reported in."""
        with self._lock:
            statements, total_ms = self.statements, self.total_ms
        divisor = requests or 1
        return {
            "requests": requests,
            "statements_total": statements,
            "statements_per_request": round(statements / divisor, 2),
            "db_execution_ms_total": round(total_ms, 3),
            "db_execution_ms_per_request": round(total_ms / divisor, 3),
            "top_shapes": [
                {**s, "count_per_request": round(s["count"] / divisor, 2)}
                for s in self.top_shapes(top)
            ],
        }


def attach(engine, profile: SqlProfile | None = None) -> SqlProfile:
    """Record every statement executed on ``engine``. Returns the profile."""
    from sqlalchemy import event

    profile = profile or SqlProfile()
    state = threading.local()

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        state.started = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        started = getattr(state, "started", None)
        elapsed_ms = (time.perf_counter() - started) * 1000.0 if started else 0.0
        # `parameters` is deliberately ignored — see the module docstring.
        profile.record(statement, elapsed_ms)

    return profile
