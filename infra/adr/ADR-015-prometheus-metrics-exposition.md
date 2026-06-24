# ADR-015 — Prometheus Metrics Exposition

- Status: Accepted (v0.13)
- Date: 2026-06-24
- Supersedes: none
- Related: ADR-004 (observability), ADR-012 (worker runtime), ADR-014 (assistant SDK)

## Context

Through v1.0 MemoryOps had three observability streams: structured JSON logs with a
secret-redacting formatter + per-request `trace_id` ([core/logging.py](../../services/api/app/core/logging.py)),
an append-only audit log, and a **per-tenant business-metrics JSON** surface at
`GET /api/metrics` ([routes/audit.py](../../services/api/app/routes/audit.py) →
`Repository.metrics(tenant_id)`). Worker activity is visible at `GET /healthz/workers`.

What was missing is the de-facto standard a monitoring stack scrapes: a
**process-wide Prometheus exposition endpoint** for operational signals (HTTP
traffic, retrieval latency, policy-decision rates, worker run counts). The
phase-10 gate listed "Prometheus/Grafana metrics" as an open v0.3+ gap. The per-
tenant JSON surface is the wrong shape for this — it is business-scoped, requires a
`tenant_id`, and is not Prometheus text.

## Decision

Add a **dependency-free** Prometheus text exposition at `GET /metrics`.

- **No new dependency.** The metrics primitives (`Counter`, `Gauge`, `Histogram`)
  and the Prometheus 0.0.4 text renderer are hand-rolled in
  `app/observability/registry.py`. This preserves the repo's lean, offline-first,
  no-keys-required posture (6 runtime deps). `prometheus_client`/OpenTelemetry were
  rejected as runtime deps for this reason.
- **Content-free, low-cardinality labels only.** Labels are bounded enums / route
  templates: `route` (the matched FastAPI route *template*, not the raw URL),
  `method`, `status_class` (`2xx`/`4xx`/`5xx`), policy `decision` (the `Decision`
  enum), retrieval `mode` (`hybrid`/`fallback`/`none`), worker run `status`. There
  are **no `tenant_id` / `user_id` labels** and no message content — both for
  privacy and to keep cardinality finite.
- **Graceful degradation (invariant #4).** All recording goes through no-throw
  helpers in `app/observability/instrument.py`; instrumenting a request can never
  raise into the request/read/write path. The scrape handler degrades to partial
  output (worker gauges omitted) if the repository is unavailable, never a 500.
- **Worker metrics are pull-derived.** Workers run in a separate process, so their
  activity is invisible to the API's in-process counters. The scrape handler reads
  the content-free `summarize_runtime_health(repo)` at scrape time instead.
- **Additive.** No `services/api` behavior changes. The existing per-tenant
  `GET /api/metrics` JSON stays as-is; the new endpoint lives at root `/metrics`
  (standard scrape path, no collision). Toggle with `MEMORYOPS_METRICS_ENABLED`.

## Consequences

- A Prometheus/Grafana stack can scrape MemoryOps with zero code, and
  `memoryops_policy_decisions_total{decision="BLOCK"}` / total yields a live
  policy-block rate, closing the metrics half of the phase-10 gap.
- The metrics surface is intentionally minimal and dependency-free; it is **not**
  OpenTelemetry tracing (deferred) and carries no token/cost economics (Phase 2).
- Hand-rolled primitives mean we own the exposition-format correctness; this is
  covered by `tests/test_metrics_endpoint.py`.

## Out of scope

- OpenTelemetry / distributed tracing.
- Token/embedding cost economics.
- An admin observability dashboard UI.
