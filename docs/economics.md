# Economics — token + cost estimation

MemoryOps AI attaches an **advisory** token + cost estimate to every chat request
(v1.2, [ADR-016](../infra/adr/ADR-016-economics-cost-estimation.md)). It builds on
the deterministic token estimator used for compression savings and the v1.1
Prometheus surface ([docs/observability.md](observability.md)).

> **Advisory, not billing.** Token counts are deterministic estimates
> (≈4 chars/token); costs are list-price *estimates*. MemoryOps never asserts a
> fixed headline cost. With the default `stub` providers there is no real cost, so
> estimates are `$0` (`priced=false`) while token counts stay real.

## On the chat response

`POST /api/chat` responses include an optional `economics` block:

```json
{
  "economics": {
    "embedding_model": "",
    "llm_model": "",
    "embedding_tokens": 6,
    "context_tokens": 0,
    "compressed_tokens": 0,
    "tokens_saved": 0,
    "llm_input_tokens": 18,
    "estimated_cost_usd": 0.0,
    "cost_saved_usd": 0.0,
    "priced": false
  }
}
```

- `embedding_tokens` — estimated tokens to embed the query (only when the read path
  embedded it, i.e. `retrieval_mode == "hybrid"`).
- `context_tokens` / `compressed_tokens` / `tokens_saved` — from the compression
  result; equal context/compressed and `0` saved when compression is off.
- `llm_input_tokens` — advisory prompt size (composed context + user message).
- `estimated_cost_usd` — embedding + LLM-input cost; `0.0` when unpriced.
- `cost_saved_usd` — `tokens_saved` valued at the LLM input rate.
- `priced` — whether the active model resolved to a price.

The Python SDK exposes this as `result.economics` on the chat result.

## Prometheus metrics

Two content-free counters appear on `GET /metrics` (labels: `kind`, `model`; **no
tenant/user labels**):

| Metric | Labels | Meaning |
|--------|--------|---------|
| `memoryops_tokens_total` | `kind` (embedding\|context\|compressed\|saved\|llm_input), `model` | Estimated tokens processed |
| `memoryops_estimated_cost_usd_total` | `kind` (request\|saved), `model` | Advisory estimated USD cost |

Useful: `rate(memoryops_estimated_cost_usd_total{kind="request"}[1h])` for spend
rate; `memoryops_estimated_cost_usd_total{kind="saved"}` for compression savings.

## Pricing

Default advisory list prices (USD per 1M tokens) live in
[app/economics/pricing.py](../services/api/app/economics/pricing.py) for the models
the runtime names (`text-embedding-3-small`, `gpt-4o-mini`,
`claude-haiku-4-5-20251001`, `gemini-1.5-flash`). Unknown / stub models are
unpriced ($0).

Override per-model prices with `MEMORYOPS_PRICING_OVERRIDES` (JSON, USD/1M):

```bash
export MEMORYOPS_PRICING_OVERRIDES='{"gpt-4o-mini":{"input":0.15,"output":0.60}}'
```

A malformed value is ignored (logged), never fatal.

## Guarantees

- **Graceful degradation (invariant #4)** — estimation is no-throw; a failure skips
  the `economics` block but never affects the chat response.
- **Content-free** — metrics carry no PII; bounded labels only.
- **Additive** — `economics` is an optional response field under the `1.x`
  additive-compatibility promise.

## Not included

- Persisted per-tenant economics ledger / `GET /api/economics` / budgets +
  enforcement (the phase-16 "→ later" gap).
- Real provider token-usage readback.
