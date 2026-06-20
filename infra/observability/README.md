# Observability (ADR-004)

Two complementary streams today, with a clear upgrade path.

## Implemented

- **Structured logs** — one JSON line per event via
  `services/api/app/core/logging.py`, with a secret-redacting formatter and a
  per-request `trace_id` (set in the gateway / HTTP middleware). Fields:
  `ts, level, logger, trace_id, tenant_id, user_id, message, event, latency_ms,
  memory_count, status`.
- **Audit log** — append-only business events in `memory_audit_logs`
  (`memory_created`, `memory_blocked`, `memory_deleted`, …).
- **Metrics** — derived counts at `GET /api/metrics` and on the admin dashboard:
  total/active/pending/blocked/deleted memories, retrieval count, audit events.

## Metrics to track (target)

```text
memory_write_count          memory_retrieval_count
memory_block_count          memory_delete_count
retrieval_latency_ms        candidate_to_saved_rate
correction_rate             memory_helpfulness_rate
```

## Upgrade path

- **Traces** — wrap span boundaries with OpenTelemetry; export to Tempo/Jaeger.
  The `trace_id` is already threaded through logs.
- **Metrics** — emit Prometheus counters/histograms; visualize in Grafana.
- **LLM traces** — send prompt/response/cost to Langfuse when provider adapters
  replace the heuristic LLM.
- **Cost** — attribute token cost per write/retrieval (economics plane).
