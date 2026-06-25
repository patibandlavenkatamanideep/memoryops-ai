# Observability

MemoryOps AI exposes four observability streams:

| Stream | Where | Shape |
|--------|-------|-------|
| Structured logs | stdout (`app/core/logging.py`) | JSON, secret-redacted, per-request `trace_id` |
| Audit log | `GET /api/audit` | Append-only governance events |
| Business metrics | `GET /api/metrics` | Per-tenant JSON counts (writes, blocks, deletes, retrievals, audit) |
| **Prometheus metrics** | **`GET /metrics`** | **Process-wide text exposition for a Prometheus/Grafana scrape** |
| Worker health | `GET /healthz/workers` | Content-free worker run history |

This page documents the Prometheus surface (v0.13, [ADR-015](../infra/adr/ADR-015-prometheus-metrics-exposition.md)).

## `GET /metrics`

Returns Prometheus text exposition (format `0.0.4`). **Process-wide, content-free,
low-cardinality** — there are no `tenant_id` / `user_id` labels and no message
content. Dependency-free (hand-rolled in `app/observability/`), so it works with
no infra and no API keys, like the rest of the stack.

Toggle with `MEMORYOPS_METRICS_ENABLED` (default `true`; `0`/`false`/`no` disables
and returns `404`).

### Metrics

| Metric | Type | Labels | Meaning |
|--------|------|--------|---------|
| `memoryops_http_requests_total` | counter | `route`, `method`, `status_class` | HTTP requests; `route` is the matched route *template* |
| `memoryops_http_request_duration_ms` | histogram | `route`, `method` | Request latency (ms) |
| `memoryops_retrieval_total` | counter | `mode` | Memory reads by mode (`hybrid`/`fallback`/`none`) |
| `memoryops_retrieval_duration_ms` | histogram | — | Read-path latency (retrieve+rank+compose, ms) |
| `memoryops_policy_decisions_total` | counter | `decision` | Policy broker decisions (`SAVE`/`BLOCK`/…) |
| `memoryops_worker_runs` | gauge | `status` | Recent worker runs by status (pull-derived) |
| `memoryops_worker_dead_letter_count` | gauge | — | Dead-lettered worker runs in recent history |
| `memoryops_worker_failed_count` | gauge | — | Failed worker runs in recent history |

### Useful derived signals

- **Policy block rate** — `memoryops_policy_decisions_total{decision="BLOCK"}` ÷
  `sum(memoryops_policy_decisions_total)`.
- **Retrieval degradation rate** — `memoryops_retrieval_total{mode="fallback"}` ÷
  `sum(memoryops_retrieval_total)` (invariant #4 in action).
- **Request latency p95** — `histogram_quantile(0.95, rate(memoryops_http_request_duration_ms_bucket[5m]))`.

### Design guarantees

- **Graceful degradation (invariant #4)** — recording a metric is no-throw and can
  never block a request. The scrape handler degrades to partial output (worker
  gauges omitted) if the repository is unavailable; it never returns `500`.
- **Worker metrics are pull-derived** — workers run in a separate process, so the
  handler reads the content-free `summarize_runtime_health(repo)` at scrape time
  rather than relying on in-process counters.
- **No PII / no secrets** — labels are bounded enums and route templates only.

## Scraping with Prometheus

```yaml
scrape_configs:
  - job_name: memoryops-api
    metrics_path: /metrics
    static_configs:
      - targets: ["api:8000"]
```

## Liveness / readiness

- `GET /healthz` — `{status, version, uptime_seconds, metrics_enabled}`.
- `GET /readyz` — repository + provider readiness rollup.
- `GET /healthz/workers` — worker run history (dead-letter / failure counts).

## Not (yet) included

- OpenTelemetry / distributed tracing (deferred).
- Token/embedding cost economics.
- An admin observability dashboard UI.
