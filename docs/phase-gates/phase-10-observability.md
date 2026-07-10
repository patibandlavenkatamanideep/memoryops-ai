# Phase 10 — Observability

**Question:** Traces, token cost, alerts, prompt inspection.

## MemoryOps mapping
Streams: append-only audit log (business events); structured JSON logs with a
secret-redacting formatter + per-request `trace_id` + `span_id`; per-tenant business
metrics at `GET /api/metrics`; a process-wide **Prometheus exposition** at `GET /metrics`
(v0.13, content-free, dependency-free; see ADR-015); and **distributed tracing** (v1.8,
ADR-022) — a dependency-free span façade with an optional OpenTelemetry bridge that
traces every lifecycle stage (write / read / admission / worker / deletion-proof) under
a correlation id, exposed content-free at `GET /api/traces`.

## Gate (must be true to pass)
- Every lifecycle action emits an audit event.
- Every request log line carries `trace_id` and never leaks secrets.
- Metrics (writes, blocks, deletes, retrievals, audit count) are queryable.
- Operational signals are scrapeable in Prometheus format at `GET /metrics`
  (HTTP traffic, retrieval latency/mode, policy-decision rate, worker runs),
  content-free and low-cardinality.
- Loop runs/events expose operational traces for memory.write, memory.read,
  memory.governance, memory.evaluation, release.gate, and learning.continuous.
- Token/cost signals are observable: context compression emits structured
  `context_compression` / `context_compression_failed` events and per-request
  savings estimates (v0.2.1; see phase-16 economics).

## Evidence
- `services/api/app/core/logging.py` (redacting JSON formatter)
- `services/api/app/services/audit.py`, `routes/audit.py`
- `services/api/app/loops/`, `routes/loops.py`
- `services/api/app/compression/metrics.py`, `services/api/app/services/gateway.py`
- `services/api/app/observability/` (registry + instrument), `routes/metrics_prometheus.py`,
  `tests/test_metrics_endpoint.py`, [docs/observability.md](../observability.md)
- [infra/observability/README.md](../../infra/observability/README.md)
- [ADR-004 observability](../../infra/adr/ADR-004-observability.md), [ADR-007 compression](../../infra/adr/ADR-007-headroom-token-compression.md), [ADR-015 Prometheus metrics](../../infra/adr/ADR-015-prometheus-metrics-exposition.md)

## Gaps to close (→ later)
- Durable span storage / sampling (delegate to the OTel backend); `traceparent`
  propagation into external LLM/vector calls; Langfuse LLM traces. OpenTelemetry
  tracing façade + `/api/traces`: ✅ done (v1.8). Prometheus/Grafana metrics: ✅ (v0.13).

## Status: ✅ Implemented (logs + audit + business + Prometheus metrics + distributed tracing; durable OTel storage delegated to the backend)
