# Changelog — MemoryOps AI

All notable releases. Git tags + GitHub Releases are the source of truth; this
file is the consolidated narrative. Versions are `vMAJOR.MINOR[.PATCH]`.

## v1.4 — Deletion Proof: Tombstone Lineage + Leakage Evals
Additive under the `1.x` compatibility promise. Extends the deletion guarantee (#2)
to *derived* artifacts. New **tombstone lineage** (`app/db/lineage.py`) records where
a memory was derived from (`parent_memory_ids`, `lineage_root_id`, `source_event_id`)
content-free in metadata, and deletion stamps an explicit audited tombstone. The
Context Admission Gate gains a `BLOCK_TOMBSTONED_ANCESTOR` verdict (ADR-017): a
memory whose lineage ancestry contains a tombstoned/deleted/purged ancestor is denied
context admission — fail-closed (a missing ancestor blocks too), transitive, and
cycle/depth-safe. The gateway supplies a tenant/user-scoped ancestry resolver that
sees soft-deleted rows; originals (no parents) skip the check. A **deleted-memory
leakage eval suite** adds two case kinds to the real harness — `leakage` (store →
use → delete → probe with direct/indirect/inference queries + re-query; the secret
must not surface in used content or the answer, and the row must never resurface) and
`derived_tombstone` (an artifact derived from a deleted memory must be blocked) —
shipped in `adversarial_cases.json` so they run in `run_evals` and the dashboard.
Defense-in-depth (only ever *removes* memory), no-throw, no DB migration.
See [docs/deletion-proof-lineage.md](docs/deletion-proof-lineage.md), [ADR-018](infra/adr/ADR-018-tombstone-lineage-deletion-proof.md).

## v1.3 — Context Admission Gate + Memory Usage Trace
Additive under the `1.x` compatibility promise. A new **Context Admission Gate**
(`app/services/admission_gate.py`) runs between the ranker and the context composer
(`retrieve → rank → [gate] → compose`) and decides, per memory, whether it is
*allowed* into context — not merely relevant. Each candidate gets an explainable
verdict (`ALLOW` or a specific `BLOCK_*`: wrong-tenant, deleted, archived, inactive,
consent-withdrawn, expired, sensitive, low-confidence); only `ALLOW` memories reach
the LLM. The gate is defense-in-depth (it only ever *removes* memory, strengthening
invariants #1/#2), no-throw (#4), and audited per turn via `context_admission_blocked`
(#7). Consent-withdrawn / retention-expired *active* memory is now denied admission
immediately, not only after the next retention-worker pass; legal hold / pin /
protect are retention-exempt. Conservative defaults change no behavior; the
sensitivity + low-confidence gates are opt-in, and `admission_gate_enabled=false`
runs it in observe-only (shadow) mode. Every chat response gains an optional
**`trace` (Memory Usage Trace)** — the permissioned, explainable memory trail behind
the answer (`memories_used` / `memories_blocked` with provenance, `stored_at`,
`consent_status`, `retention_status`, `admission_decision`/`reason`, score breakdown)
— plus a content-free `memoryops_admission_decisions_total{decision}` Prometheus
counter and a Playground audit-trail view. Toggle with `MEMORYOPS_ADMISSION_GATE` /
`MEMORYOPS_MEMORY_TRACE`. No DB migration; no chat-path behavior change.
See [docs/context-admission-gate.md](docs/context-admission-gate.md), [ADR-017](infra/adr/ADR-017-context-admission-gate.md).

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
