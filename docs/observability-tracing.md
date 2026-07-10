# Full memory observability — tracing

Prometheus metrics (v1.1) tell you *how much*. Tracing (v1.8,
[ADR-022](../infra/adr/ADR-022-observability-tracing.md)) tells you *what happened to
this one turn* — every memory-lifecycle stage, correlated end to end.

Each request or worker run is one **correlation id**; each stage — write, retrieve,
rank, admission, compose, worker jobs, deletion-proof checks — is a **span** under it.

## Three correlated signals

| Signal | Where | Correlated by |
| --- | --- | --- |
| Structured logs | stdout (JSON) | `trace_id` + `span_id` |
| Spans | `GET /api/traces` (+ OpenTelemetry) | `correlation_id` (= request `trace_id`) |
| Metrics | `GET /metrics` (Prometheus) | low-cardinality labels |

A chat turn returns `x-trace-id`; pass it to `GET /api/traces?correlation_id=<id>` to
see exactly the spans for that turn.

## Content-free by construction

Spans carry **counts, modes, decisions, and phase names only** — never memory content,
message text, or raw tenant/user ids. That is what makes `GET /api/traces` safe to
expose and the same reason the Prometheus surface avoids tenant labels. Recording is
**no-throw** (invariant #4): a span records an `error` status and re-raises; it never
turns a traced failure into a different one.

## What you see for one turn

```jsonc
// GET /api/traces?correlation_id=turn-1
{ "count": 6, "spans": [
  { "name": "memory.read",           "correlation_id": "turn-1", "parent_span_id": null, "duration_ms": 3 },
  { "name": "retrieve",  "attributes": {"mode": "hybrid", "candidates": 4}, "parent_span_id": "…" },
  { "name": "rank",                                                         "parent_span_id": "…" },
  { "name": "admission", "attributes": {"admitted": 2, "blocked": 1},       "parent_span_id": "…" },
  { "name": "compose",                                                      "parent_span_id": "…" },
  { "name": "memory.write.extract", "attributes": {"candidates": 1},        "parent_span_id": null }
]}
```

Worker runs trace the same way under a minted `worker-…` correlation id, one
`worker.job` span per job.

## Turning on real OpenTelemetry

In-process recording is dependency-free and on by default. To export the *same* spans
to Jaeger / Tempo / Honeycomb / Datadog, install the OTel SDK and enable it:

```bash
pip install opentelemetry-sdk opentelemetry-exporter-otlp
export MEMORYOPS_OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_SERVICE_NAME=memoryops-api
```

MemoryOps emits spans through the standard `opentelemetry` tracer; your usual SDK env
vars (endpoint, headers, sampling) apply. With the SDK absent or `otel_enabled` false,
the in-process buffer is the only sink — no dependency, no config.

### Example: OpenTelemetry Collector → Jaeger

```yaml
# otel-collector.yaml
receivers:
  otlp:
    protocols: { grpc: { endpoint: 0.0.0.0:4317 } }
exporters:
  otlp/jaeger: { endpoint: jaeger:4317, tls: { insecure: true } }
service:
  pipelines:
    traces: { receivers: [otlp], exporters: [otlp/jaeger] }
```

Then open Jaeger and filter by service `memoryops-api`; each trace is one chat turn or
worker run, with the read/write/admission spans nested inside.

## Toggles

| Env | Default | Effect |
| --- | --- | --- |
| `MEMORYOPS_TRACING_ENABLED` | `true` | in-process span recording + `/api/traces` |
| `MEMORYOPS_OTEL_ENABLED` | `false` | also export to an OpenTelemetry backend (SDK required) |

## Limits

- The in-process buffer holds the most recent 512 spans (a live tail, not durable
  storage) — use OTel export for retention and cross-service traces.
- Spans are content-free by design; to inspect *which* memories were used or blocked,
  use the per-turn [Memory Usage Trace](context-admission-gate.md) on the chat response.
