# ADR-022 — Full Memory Observability: Distributed Tracing

- Status: Accepted (v1.8)
- Date: 2026-07-09
- Supersedes: none
- Related: ADR-015 (Prometheus metrics), ADR-004 (audit + trace context), ADR-017
  (admission gate + usage trace)

## Context

MemoryOps already had structured JSON logs with a `trace_id` contextvar and a
content-free Prometheus surface. What was missing was *causal* observability: for a
single turn, which stages ran, in what order, how long each took, and how a worker run
or deletion-proof check relates to them. Metrics answer "how much"; they cannot answer
"what happened to this request." Adding raw OpenTelemetry as a hard dependency would
break the project's offline/no-keys principle and its tests.

## Decision

Add a **dependency-free tracing façade** with an **optional OpenTelemetry bridge**
(`app/observability/tracing.py`).

- **Spans under a correlation id.** `span(name, **attrs)` opens a span parented to the
  current one (contextvars), records duration + status on exit, and appends it to a
  bounded in-process ring buffer. The correlation id is the request `trace_id` (set by
  the HTTP middleware and by `Gateway.handle_chat`) or a freshly minted `worker-…` id
  for background jobs — so a chat turn or a worker run is one correlated trace.
- **Content-free + low-cardinality.** Span attributes are counts / modes / decisions /
  phase names only — never memory content, message text, or raw tenant/user ids. This
  is what makes `GET /api/traces` safe to expose.
- **No-throw (invariant #4).** Recording never raises; a span records `error` status
  and re-raises the original exception. Tracing config errors degrade to a no-op.
- **Optional OTel export.** If the OpenTelemetry SDK is installed *and* `otel_enabled`,
  the same spans are emitted through the standard `opentelemetry` tracer to the
  operator's real backend (Jaeger/Tempo/Honeycomb/Datadog). Absent or disabled, the
  in-process buffer is the only sink — no dependency, offline tests unaffected.
- **Lifecycle instrumentation.** The gateway wraps the read path
  (`memory.read` → retrieve / rank / admission / compose) and the write path
  (`memory.write.extract` / `memory.write.commit`); the worker runner wraps each job
  (`worker.job`). Logs gain a `span_id` so a log line ties to its span.
- **`GET /api/traces`.** Recent spans, filterable by `correlation_id`, plus a
  dashboard/OTel-collector recipe in `docs/observability-tracing.md`.

## Consequences

- Every lifecycle decision is now traceable across API, retrieval, admission, workers,
  and deletion — correlated with logs and metrics.
- Additive + backward compatible: on by default but content-free and cheap; no schema
  change, no new hard dependency; all prior tests pass, +10 new.
- Real distributed tracing is one `pip install` + one env var away, without MemoryOps
  taking an OTel dependency itself.
- Cost: a dict + deque append per span (bounded 512), negligible on the request path.

## Out of scope (later)

- Durable span storage / sampling policy (delegated to the OTel backend).
- Trace-context propagation *into* external LLM/vector calls (W3C `traceparent`);
  the façade is ready for it but adapters don't inject headers yet.
- Auto-instrumentation of every module — instrumentation is at the orchestration
  seams (gateway, worker runner) where the lifecycle is visible.
