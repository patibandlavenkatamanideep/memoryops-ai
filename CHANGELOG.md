# Changelog — MemoryOps AI

All notable releases. Git tags + GitHub Releases are the source of truth; this
file is the consolidated narrative. Versions are `vMAJOR.MINOR[.PATCH]`.

## v2.2 — Public Benchmark + Examples
Additive under the `1.x` compatibility promise. Turns MemoryOps' *measured* governance
into a public, reproducible artifact. A new **benchmark** (`benchmark/run_benchmark.py`)
reuses the real eval harness (no new eval logic) and scores every case into named
governance suites — **deletion_and_leakage**, **tenant_isolation**, **context_admission**,
**policy_governance**, **retrieval_quality** — emitting a human scorecard/leaderboard, a
`--json` machine format, and a committed `benchmark/SCORECARD.md` (currently **32/32,
100%, critical suites perfect**). The two **critical** suites (deletion/leakage +
tenant isolation) must be perfect or the benchmark exits non-zero, and a test asserts
**every eval kind maps to a suite** so coverage can't silently drop. Suites are defined
by outcome, so another memory system can implement the same case kinds and fill in the
same table — the deletion-leakage "leaderboard" per entrant. Two domain examples ship in
the SDK: an **enterprise assistant** and a **regulated (healthcare/legal/finance) memory
demo** — governed recall, audience-scoped disclosure, verifiable erasure, tamper-evident
audit, end to end. +5 tests (`tests/test_benchmark.py`); full suite 360 passed. See
[benchmark/README.md](benchmark/README.md), [ADR-026](infra/adr/ADR-026-public-benchmark.md).

## v2.1 — Agent Framework Integrations
Additive under the `1.x` compatibility promise. Makes MemoryOps easy to plug into real
agent systems as the **governed memory layer** — one framework-agnostic adapter plus
per-framework examples, not six bespoke SDKs. New `memoryops.GovernedMemory` exposes a
uniform `remember` / `recall` / `context_for` / `answer` / `forget` / `withdraw_consent`
surface over `MemoryOpsClient`, carries an `audience` (applied to every recall via the
v1.9 Recall Gate), and adds **no** governance — the server stays authoritative.
`GovernedMemory.for_audience(...)` gives a per-agent clearance view over one store (e.g.
a customer-facing agent gets `public`, an internal agent `private`). The SDK `chat()`
gains an additive `audience` parameter. Runnable, import-guarded examples ship for
**LangGraph, LlamaIndex, CrewAI, AutoGen, Semantic Kernel, and the OpenAI Agents SDK**
(`packages/memoryops-sdk/examples/integrations/`), each wrapping the adapter into that
framework's memory/tool/plugin interface. The adapter is tested against the real
in-process app (`tests/test_integrations.py`, +5). See [docs/agent-integrations.md](docs/agent-integrations.md), [ADR-025](infra/adr/ADR-025-agent-framework-integrations.md).

## v2.0 — Enterprise Evidence Layer
Additive under the `1.x` compatibility promise. Makes MemoryOps' governance
**verifiable**, not just claimed — security-reviewable and compliance-friendly. Adds a
**tamper-evident audit hash chain** (`app/evidence/hashchain.py`): every audit event
links to the previous one in its tenant's chain
(`entry_hash = SHA-256(canonical(event) + prev_hash)`), set in `repo.add_audit` so all
audited actions are covered; `verify_chain` reconstructs order from the links (robust to
timestamp ties) and detects any edit / deletion / insertion / reorder. Two new
`StoredAudit` fields (`prev_hash`, `entry_hash`). Read-only, tenant-scoped **evidence
reports** (`app/evidence/reports.py`, `app/routes/evidence.py`): per-response
**evidence bundle** (`GET /api/evidence/response/{trace_id}`), **deletion proof**
(`/deletion/{memory_id}`), **policy report** (`/policy`), **lifecycle export**
(`/lifecycle/{memory_id}`), and chain **verification** (`/audit/verify`) — each
`enforce_scope`-guarded, content-minimizing (previews + ids + decisions, never full
secrets). The admin evidence dashboard consumes these JSON endpoints. Tamper-evidence,
not tamper-proofing (pin the head hash externally for stronger guarantees). +8 tests
(`tests/test_evidence_layer.py`); full suite 353 passed. See [docs/enterprise-evidence.md](docs/enterprise-evidence.md), [ADR-024](infra/adr/ADR-024-enterprise-evidence-layer.md).

## v1.9 — Recall Gate + Output Gate
Additive under the `1.x` compatibility promise; on by default but no-op unless there is
something to protect (default `private` audience + an honest model → unchanged). Adds
governance on **both** edges of generation. The **Recall Gate**
(`app/services/recall_gate.py`) makes context entry *audience-aware*: each request
carries an `audience` (`private` | `team` | `public`) and a memory is recalled only if
its `sensitivity` is within that clearance (`private`=low+med+high, `team`=low+med,
`public`=low) — withheld memories surface in the Memory Usage Trace with a new
`BLOCK_AUDIENCE` decision, reusing the existing trace/metrics/audit path. The **Output
Gate** (`app/services/output_gate.py`) is the mirror on the way out: it inspects the
generated answer and, when it shares a distinctive contiguous phrase (≥4 significant
words) with a memory the gates blocked, **redacts** the spans (default) or **refuses**
with a safe message — deterministic, no-throw, audited (`output_gate_blocked`), and
surfaced as an optional `output_gate` block. `ChatRequest.audience` +
`ChatResponse.output_gate` are additive. Toggles `MEMORYOPS_RECALL_GATE`,
`MEMORYOPS_OUTPUT_GATE`, `MEMORYOPS_OUTPUT_GATE_MODE`. +9 tests
(`tests/test_recall_output_gates.py`); full suite 344 passed. See [docs/recall-output-gates.md](docs/recall-output-gates.md), [ADR-023](infra/adr/ADR-023-recall-output-gates.md).

## v1.8 — Full Memory Observability (Distributed Tracing)
Additive under the `1.x` compatibility promise; on by default but content-free and
dependency-free. Metrics (v1.1) tell you *how much*; v1.8 tracing tells you *what
happened to one turn*. A dependency-free tracing façade (`app/observability/tracing.py`)
opens a **span** for every memory-lifecycle stage — write (`memory.write.extract` /
`.commit`), read (`memory.read` → `retrieve` / `rank` / `admission` / `compose`), and
`worker.job` — under a **correlation id** (the request `trace_id`, or a minted
`worker-…` id for background jobs), so a chat turn or worker run is one correlated
trace. Spans are **content-free + low-cardinality** (counts / modes / decisions / phase
names only — never memory content or raw tenant/user ids) and recording is **no-throw**
(invariant #4). Structured logs gain a `span_id`; the whole trail is exposed at
**`GET /api/traces`** (filterable by `correlation_id`). If the OpenTelemetry SDK is
installed and `MEMORYOPS_OTEL_ENABLED=true`, the same spans export to your real backend
(Jaeger/Tempo/Honeycomb/Datadog) — otherwise the in-process 512-span ring buffer is the
only sink, no dependency. Toggle `MEMORYOPS_TRACING_ENABLED`. +10 tests
(`tests/test_tracing.py`); full suite 333 passed. See [docs/observability-tracing.md](docs/observability-tracing.md), [ADR-022](infra/adr/ADR-022-observability-tracing.md).

## v1.7 — Storage / Vector Backend Abstraction
Additive under the `1.x` compatibility promise; default unchanged. Makes MemoryOps
portable across vector stores **without weakening any governance guarantee**, by
splitting retrieval into an authoritative `Repository` (memory metadata, governance,
tombstone lineage, audit, workers — still the single enforcement point for isolation +
deletion) and a narrow, swappable **`VectorIndex`** seam (`app/db/vector/`) that
abstracts only nearest-neighbour search and holds **ids + embeddings only** (never
content/consent/lineage). After the index returns candidate ids the repository + the
admission gate re-check every one, so a stale index entry can't leak content. A written
contract in `base.py` (tenant isolation, deletion non-reappearance, no-bypass, graceful
degradation) is proven by `assert_vector_index_contract` — a reusable conformance suite
any backend must pass. The in-memory backend **actually uses** the seam (an
`InMemoryVectorIndex` maintained across create/update/delete/compaction), so it is
load-bearing, not decorative, and every retrieval test exercises it. Optional,
**import-guarded** adapters ship for **Qdrant, LanceDB, and Weaviate** (Pinecone is the
same shape); with no client installed they report unavailable and the factory falls back
to in-memory (invariant #4). Select with `MEMORYOPS_VECTOR_INDEX=memory|qdrant|lancedb|weaviate`.
+5 tests (`tests/test_vector_index.py`); full suite 321 passed. See [docs/storage-backends.md](docs/storage-backends.md), [ADR-021](infra/adr/ADR-021-vector-backend-abstraction.md).

## v1.6 — Auth + Authorization Adapters
Additive under the `1.x` compatibility promise; **off by default** so no behavior
changes until an operator opts in. MemoryOps previously trusted `tenant_id`/`user_id`
from the caller — fine behind a trusted boundary, but not enough to run behind real
user identity. v1.6 adds an **identity-neutral** auth layer (`app/auth/`) that verifies
an externally-minted identity and enforces that every operation is scoped to the
authenticated tenant/user. Two modes via `MEMORYOPS_AUTH_MODE`: `trusted_header` (an
authenticated upstream proxy injects `X-MemoryOps-Tenant`/`X-MemoryOps-User` — the
bring-your-own-auth pattern) and `jwt` (MemoryOps verifies an `Authorization: Bearer`
token and maps configured claims, dotted paths allowed, to the principal).
JWT verification is **dependency-free** for HS256/384/512 (stdlib `hmac`, tests need
no keys); RS\* works when `cryptography` is present. A **scope-validation middleware**
authenticates every `/api/*` request and checks any `tenant_id`/`user_id` in the query
string; body routes (`chat`, `retention`) call `enforce_scope()` after parsing — a
mismatch is `403`, a missing/invalid credential is `401`, never a `500`. Adapters ship
as copy-paste env recipes (Clerk / Auth0 / Supabase / BYO), not a bespoke SDK. New
tests in `tests/test_auth.py`. See [docs/auth-adapters.md](docs/auth-adapters.md), [ADR-020](infra/adr/ADR-020-auth-authorization-adapters.md).

## v1.5 — Deleted / Expired Memory Leakage Evals
Additive under the `1.x` compatibility promise. Makes the deletion guarantee (#2)
*measurable* rather than merely asserted — most memory systems claim deletion, few
test whether a deleted or expired memory can still influence output. Builds on v1.4's
tombstone lineage (no new runtime mechanism) with a poison-memory battery and three
new proofs in the real eval harness (`app/services/eval_harness.py`, shipped in
`adversarial_cases.json` so they run in `run_evals` and the dashboard):
**`cross_session_leakage`** — a deleted memory must not leak into a brand-new session
(a fresh `Gateway`/read stack rebuilt on the same store; this also proves
reindex/rebuild non-reappearance); **`expiry_leakage`** — a retention-expired or
consent-withdrawn *active* memory is denied context admission (`BLOCK_EXPIRED` /
`BLOCK_CONSENT_WITHDRAWN`) without being deleted (expiry ≠ deletion); and a transitive
**`derived_tombstone`** (`chain_depth`) — deleting the *root* of a `root → … → leaf`
lineage chain blocks a grandchild summary, proving lineage blocking walks the whole
chain. Every case carries its own teeth (the secret must be *used* before
deletion/expiry, so a pass is never vacuous), and the leakage family is now
release-gating (`_CRITICAL_KINDS`). New unit proofs in
`tests/test_deleted_memory_leakage_evals.py` assert the admission *decision* in the
Memory Usage Trace, not just the used-memory list. Deterministic + offline (stub
stack, no API keys); no schema or chat-path change.
See [docs/deleted-memory-leakage-evals.md](docs/deleted-memory-leakage-evals.md), [ADR-019](infra/adr/ADR-019-deleted-memory-leakage-evals.md).

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
