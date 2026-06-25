# ADR-016 — Advisory Economics: Token + Cost Estimation

- Status: Accepted (v1.2)
- Date: 2026-06-25
- Supersedes: none
- Related: ADR-015 (Prometheus metrics), ADR-007 (Headroom compression), ADR-008 (LLM providers)

## Context

Phase 16's per-request **compression savings** instrumentation already ships
(`Compression` block on `ChatResponse`, ADR-007). The phase-16 gate's own
"→ later" list still named **token/cost estimation across the whole request** and
**cost-per-request rollups**. With the v1.1 Prometheus surface (ADR-015) now
present, there is a natural substrate to expose cost economics.

## Decision

Add a small, **advisory** economics layer (`app/economics/`) that estimates token
usage and USD cost per chat request, surfaces it on the response and as Prometheus
counters, and reuses existing primitives.

- **Advisory, not billing.** Token counts reuse the deterministic
  `compression.metrics.estimate_tokens` (≈4 chars/token). Costs are *list-price
  estimates* from a configurable table; no fixed headline number is asserted
  (consistent with ADR-007 / `docs/token-compression.md`).
- **Default price table + override.** `pricing.py` ships advisory USD/1M-token
  prices for the models `core/config.py` already names (embeddings
  `text-embedding-3-small`; LLMs `gpt-4o-mini`, `claude-haiku-4-5-20251001`,
  `gemini-1.5-flash`). Unknown / stub models are **unpriced** ($0) — tokens are
  still counted. Operators override per-model prices via
  `MEMORYOPS_PRICING_OVERRIDES` (JSON).
- **Graceful degradation (invariant #4).** Estimation + recording is wrapped
  no-throw in the gateway; it can never block or fail a chat. A malformed override
  is ignored, not fatal.
- **Content-free metrics.** New `memoryops_tokens_total{kind,model}` and
  `memoryops_estimated_cost_usd_total{kind,model}` counters use bounded labels
  only — no `tenant_id`/`user_id`, no content (extends ADR-015's guarantees).
- **Additive.** Optional `economics` block on `ChatResponse` (responses only gain
  fields, per the `1.x` promise) and a parsed `economics` accessor in the SDK.
  No behavior change; the LLM/policy/governance paths are untouched.
- **Lean scope.** No DB migration and **no persisted per-tenant economics ledger**
  — per-tenant budgets/dashboards remain the phase-16 "→ later" gap.

## Consequences

- Every chat carries a token + (advisory) cost estimate, and an operator can graph
  process-wide token/cost on the existing Prometheus scrape — closing the
  cost-per-request half of the phase-16 gap.
- Estimates are deterministic and offline-safe: with the default stub providers,
  token counts are real and cost is `$0`/unpriced, so tests need no keys.
- We own price-table freshness; prices are documented as advisory and overridable.

## Out of scope

- Persisted per-tenant economics ledger / `GET /api/economics` / budget enforcement.
- Real provider token-usage readback (providers' `usage` is optional/advisory).
- OpenTelemetry tracing.
