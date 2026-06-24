# Phase 10 — Observability

**Question:** Traces, token cost, alerts, prompt inspection.

## MemoryOps mapping
Streams: append-only audit log (business events); structured JSON logs with a
secret-redacting formatter + per-request `trace_id`; per-tenant business metrics
at `GET /api/metrics`; and a process-wide **Prometheus exposition** at `GET /metrics`
(v0.13, content-free, dependency-free; see ADR-015).

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
- OpenTelemetry traces → Tempo/Jaeger; Langfuse LLM traces; per-write/retrieval
  cost attribution (economics). Prometheus/Grafana metrics: ✅ done (v0.13).

## Status: 🟡 Partial (logs + audit + business + Prometheus metrics done; OTel/Langfuse/economics roadmap)
