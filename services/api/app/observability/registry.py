"""Dependency-free, in-process metrics registry + Prometheus text exposition.

Deliberately hand-rolled (no ``prometheus_client`` / OpenTelemetry dependency) to
preserve the repo's lean, offline-first posture (invariant: works with no infra,
no keys). The registry holds process-wide, **content-free, low-cardinality**
signals only — labels are bounded enums/route templates, never ``tenant_id`` /
``user_id`` / message content (privacy + cardinality).

All instances are process-global and thread-safe. Recording is cheap and must
never raise into a request path — call sites should go through ``instrument.py``,
which wraps every record in a no-throw guard (graceful degradation, invariant #4).
"""

from __future__ import annotations

import threading
from collections import defaultdict

# Latency buckets in milliseconds (cumulative "less-than-or-equal" upper bounds).
# Tuned for in-process governed-memory latencies (sub-ms to a few seconds).
LATENCY_BUCKETS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000)

# A label set is an ordered tuple of (name, value) pairs, kept sorted so the same
# logical labels always hash to the same key regardless of call-site order.
LabelKey = tuple[tuple[str, str], ...]


def _key(labels: dict[str, str] | None) -> LabelKey:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


class Counter:
    """Monotonically increasing value, partitioned by label set."""

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._values: dict[LabelKey, float] = defaultdict(float)
        self._lock = threading.Lock()

    def inc(self, labels: dict[str, str] | None = None, amount: float = 1.0) -> None:
        with self._lock:
            self._values[_key(labels)] += amount

    def samples(self) -> list[tuple[LabelKey, float]]:
        with self._lock:
            return list(self._values.items())


class Gauge:
    """Point-in-time value that can go up or down, partitioned by label set.

    Used for pull-derived scrape-time values (e.g. worker run history), so it
    supports ``set`` and a ``reset`` to clear stale label sets before a refresh.
    """

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help_text = help_text
        self._values: dict[LabelKey, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._values[_key(labels)] = value

    def reset(self) -> None:
        with self._lock:
            self._values.clear()

    def samples(self) -> list[tuple[LabelKey, float]]:
        with self._lock:
            return list(self._values.items())


class Histogram:
    """Cumulative-bucket histogram (Prometheus semantics), partitioned by labels.

    Tracks per-bucket counts plus ``_sum`` and ``_count`` so quantiles/averages
    are computable downstream. Buckets are cumulative on render (``le``).
    """

    def __init__(
        self, name: str, help_text: str, buckets: tuple[float, ...] = LATENCY_BUCKETS_MS
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.buckets = buckets
        self._counts: dict[LabelKey, list[int]] = defaultdict(lambda: [0] * len(buckets))
        self._sum: dict[LabelKey, float] = defaultdict(float)
        self._total: dict[LabelKey, int] = defaultdict(int)
        self._lock = threading.Lock()

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        k = _key(labels)
        with self._lock:
            counts = self._counts[k]
            for i, upper in enumerate(self.buckets):
                if value <= upper:
                    counts[i] += 1
            self._sum[k] += value
            self._total[k] += 1

    def samples(self) -> list[tuple[LabelKey, list[int], float, int]]:
        """Returns (labels, per-bucket counts, sum, total) per label set."""
        with self._lock:
            return [
                (k, list(self._counts[k]), self._sum[k], self._total[k])
                for k in self._total
            ]


class Registry:
    """Holds the declared metric instances and renders them as Prometheus text."""

    def __init__(self) -> None:
        self.counters: list[Counter] = []
        self.gauges: list[Gauge] = []
        self.histograms: list[Histogram] = []

    def counter(self, name: str, help_text: str) -> Counter:
        c = Counter(name, help_text)
        self.counters.append(c)
        return c

    def gauge(self, name: str, help_text: str) -> Gauge:
        g = Gauge(name, help_text)
        self.gauges.append(g)
        return g

    def histogram(
        self, name: str, help_text: str, buckets: tuple[float, ...] = LATENCY_BUCKETS_MS
    ) -> Histogram:
        h = Histogram(name, help_text, buckets)
        self.histograms.append(h)
        return h


def _fmt_labels(labels: LabelKey, extra: tuple[str, str] | None = None) -> str:
    pairs = list(labels)
    if extra is not None:
        pairs = pairs + [extra]
    if not pairs:
        return ""
    inner = ",".join(f'{name}="{_escape(value)}"' for name, value in pairs)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_num(value: float) -> str:
    # Render integer-valued floats without a trailing ".0" for cleaner output.
    if value == int(value):
        return str(int(value))
    return repr(value)


def render_prometheus(registry: Registry) -> str:
    """Render the registry in Prometheus text exposition format (v0.0.4)."""
    lines: list[str] = []

    for c in registry.counters:
        lines.append(f"# HELP {c.name} {c.help_text}")
        lines.append(f"# TYPE {c.name} counter")
        samples = c.samples()
        if not samples:
            lines.append(f"{c.name} 0")
        for labels, value in samples:
            lines.append(f"{c.name}{_fmt_labels(labels)} {_fmt_num(value)}")

    for g in registry.gauges:
        lines.append(f"# HELP {g.name} {g.help_text}")
        lines.append(f"# TYPE {g.name} gauge")
        for labels, value in g.samples():
            lines.append(f"{g.name}{_fmt_labels(labels)} {_fmt_num(value)}")

    for h in registry.histograms:
        lines.append(f"# HELP {h.name} {h.help_text}")
        lines.append(f"# TYPE {h.name} histogram")
        for labels, counts, total_sum, total in h.samples():
            cumulative = 0
            for i, upper in enumerate(h.buckets):
                cumulative += counts[i]
                le = "+Inf" if upper == float("inf") else _fmt_num(upper)
                lines.append(
                    f"{h.name}_bucket{_fmt_labels(labels, ('le', le))} {cumulative}"
                )
            # +Inf bucket always equals the total observation count.
            lines.append(
                f"{h.name}_bucket{_fmt_labels(labels, ('le', '+Inf'))} {total}"
            )
            lines.append(f"{h.name}_sum{_fmt_labels(labels)} {_fmt_num(total_sum)}")
            lines.append(f"{h.name}_count{_fmt_labels(labels)} {total}")

    return "\n".join(lines) + "\n"


# ── Process-global registry + declared metrics ─────────────────────────────────
REGISTRY = Registry()

HTTP_REQUESTS_TOTAL = REGISTRY.counter(
    "memoryops_http_requests_total",
    "Total HTTP requests handled, by route template, method, and status class.",
)
HTTP_REQUEST_DURATION_MS = REGISTRY.histogram(
    "memoryops_http_request_duration_ms",
    "HTTP request handling latency in milliseconds, by route and method.",
)
RETRIEVAL_TOTAL = REGISTRY.counter(
    "memoryops_retrieval_total",
    "Memory retrieval attempts, by mode (hybrid|fallback|none).",
)
RETRIEVAL_DURATION_MS = REGISTRY.histogram(
    "memoryops_retrieval_duration_ms",
    "Memory read-path latency in milliseconds (retrieve+rank+compose).",
)
POLICY_DECISIONS_TOTAL = REGISTRY.counter(
    "memoryops_policy_decisions_total",
    "Policy broker decisions, by decision (SAVE|BLOCK|...). BLOCK/total = block rate.",
)
TOKENS_TOTAL = REGISTRY.counter(
    "memoryops_tokens_total",
    "Estimated tokens processed, by kind (embedding|context|compressed|saved|llm_input) and model.",
)
ESTIMATED_COST_USD_TOTAL = REGISTRY.counter(
    "memoryops_estimated_cost_usd_total",
    "Advisory estimated USD cost, by kind (embedding|llm_input|saved) and model. Not billing.",
)
WORKER_RUNS = REGISTRY.gauge(
    "memoryops_worker_runs",
    "Recent worker runs observed in persisted history, by status (pull-derived).",
)
WORKER_DEAD_LETTER = REGISTRY.gauge(
    "memoryops_worker_dead_letter_count",
    "Dead-lettered worker runs in recent history (pull-derived).",
)
WORKER_FAILED = REGISTRY.gauge(
    "memoryops_worker_failed_count",
    "Failed worker runs in recent history (pull-derived).",
)
