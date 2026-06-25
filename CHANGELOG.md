# Changelog — MemoryOps AI

All notable releases. Git tags + GitHub Releases are the source of truth; this
file is the consolidated narrative. Versions are `vMAJOR.MINOR[.PATCH]`.

## v1.2 — Advisory Economics: Token + Cost Estimation
Additive under the `1.x` compatibility promise. Every chat response gains an
optional `economics` block — advisory per-request token counts (embedding, context,
compressed, saved, LLM input) and estimated USD cost — and the same signals roll up
as content-free Prometheus counters (`memoryops_tokens_total`,
`memoryops_estimated_cost_usd_total`) on `GET /metrics`. Costs are list-price
*estimates*, never billing: unknown/stub models are unpriced ($0) while token counts
stay real; override prices with `MEMORYOPS_PRICING_OVERRIDES`. Reuses the
deterministic token estimator; estimation is no-throw and never affects the chat
path. SDK exposes `result.economics`. No DB migration; per-tenant budgets remain a
later item. See [docs/economics.md](docs/economics.md), [ADR-016](infra/adr/ADR-016-economics-cost-estimation.md).

## v1.1 — Prometheus Metrics Exposition
Additive under the `1.x` compatibility promise. Process-wide, content-free
Prometheus text metrics at `GET /metrics` (HTTP traffic, retrieval latency/mode,
policy-decision rate, pull-derived worker run counts) for a Prometheus/Grafana
scrape. Dependency-free (hand-rolled in `app/observability/`), low-cardinality
(no `tenant_id`/`user_id` labels), and graceful — recording is no-throw and the
scrape never 500s. `/healthz` now reports `uptime_seconds` + `metrics_enabled`.
Toggle with `MEMORYOPS_METRICS_ENABLED`. No chat-path behavior change; distinct
from the per-tenant `GET /api/metrics` JSON.
See [docs/observability.md](docs/observability.md), [ADR-015](infra/adr/ADR-015-prometheus-metrics-exposition.md).

## v1.0 — Production-Ready Governed Memory Runtime
The stable public release. The governed memory lifecycle (Capture → Evaluate →
Store → Retrieve → Rank → Compose → Update → Forget → Audit), its seven enforced
invariants, and the security/governance/reliability/observability/evaluation
planes are implemented, tested, and operable.

- **Stable contracts** — the public HTTP API and Python SDK are declared stable
  under a `1.x` additive-compatibility promise ([docs/api-stability.md](docs/api-stability.md)).
  Package versions bumped to `1.0.0`.
- **Release-readiness docs** — consolidated [known limitations](docs/limitations.md),
  a [production-readiness](docs/production-readiness.md) map (invariant → where
  enforced; production-capable vs demo-only), and this changelog.
- No behavior changes vs v0.12 — v1.0 is stabilization, documentation, and the
  stability guarantee.

## v0.12 — Interactive Playground + Hosted Demo
Interactive public Playground (`apps/playground`) that drives the real governed
pipeline in-process against a fresh in-memory store per session — capture → ask →
govern (legal hold / consent / delete / run workers) → audit trace. Demo-only;
safe to host (no DB/secrets/real data). See [docs/playground.md](docs/playground.md).

## v0.11 — Assistant SDK + Integration Examples
Typed Python SDK (`packages/memoryops-sdk`) over the governed HTTP API with
tenant/user scope injection, typed errors, and `.raw`-preserving models. Examples:
quickstart, FastAPI, RAG, agent memory. Additive only.

## v0.10 — Retention Policies + Legal Hold + Consent-Aware Memory
Retention policy packs (sensitivity → window) driving an off-by-default retention
worker; legal hold as a fail-closed preservation override (API delete → 409);
consent withdrawal/expiry drives deletion eligibility. Governance state is
metadata-driven (migration `007`). See [docs/retention-policies.md](docs/retention-policies.md).

## v0.9 — Public Results Dashboard + Evidence Explorer
Read-only Streamlit evidence dashboard (`apps/results-dashboard`) — lifecycle,
deletion-compaction proof, worker runtime, audit, validation, limitations.
Static demo data; demo-only.

## v0.8 — Worker Runtime + Scheduled Lifecycle Orchestration
Lifecycle jobs made operable: leases (no duplicate runs), retry/backoff,
dead-letter, persisted run history, `GET /healthz/workers`. Migration `006`.

## v0.7 — Deletion Compaction + Vector Purge Verification
Clears soft-deleted content + vector material after a retention window, preserves
the governance tombstone, and verifies the purge fail-closed. Not crypto-shred.

## v0.6 — Background Memory Lifecycle Workers
Decay, archive, deletion verification, conflict scan, proposal-only reflection —
tenant-scoped, idempotent, retry-safe, audited; off the chat path.

## v0.5 — Governance UI + Memory Control Plane
Next.js memory control plane: memories, governance queue, audit viewer,
per-memory provenance; additive read routes. Official product UI.

## v0.4 — Provider LLM Adapters + Structured Memory Intelligence
Provider-neutral LLM layer (stub default; optional OpenAI/Anthropic/Gemini),
schema-validated structured extraction + conflict detection. LLM output advisory.

## v0.3.2 — Railway-Only Deployment Alignment
One Railway project, five services; no Vercel.

## v0.3.1 — Loop Engineering
Memory workflows modeled as Observe → Decide → Act → Verify → Audit → Learn loops;
`/api/loops` timelines.

## v0.3 — pgvector Retrieval + RLS / Tenant Enforcement
pgvector candidate search; Postgres RLS enforced (`FORCE` + tenant policy).

## v0.2.1 — Context Compression
Optional headroom context compression at the LLM boundary; default no-op, runs
after governance, never before the policy broker.

## v0.2 — Agentic Governance + Hermes Operator Layer
Operator/developer skills, agentic-swe-kit phase gates, and the PR Invariant
Evidence Gate around the core.

## v0.1 — Governed Memory Path
The write/read path: extractor → policy broker → write service → typed store →
audit; retriever → ranker → composer. The seven invariants land.
