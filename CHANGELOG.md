# Changelog — MemoryOps AI

All notable releases. Git tags + GitHub Releases are the source of truth; this
file is the consolidated narrative. Versions are `vMAJOR.MINOR[.PATCH]`.

## Unreleased — API authorization boundary

- **Every route is classified, and the classification is enforced in CI.**
  `app/auth/authz_spec.py` states each route's scope (public / authenticated /
  self / subject / tenant / resource / operator), its required permission, and
  whether it is enforced or still planned. A route added without a spec fails the
  build, and `docs/security/endpoint-authorization-matrix.md` is generated from
  the spec rather than maintained by hand, so the published matrix cannot drift
  from the code.
- **Four authorization helpers** (`app/auth/decisions.py`) replace ad-hoc checks:
  a fixed capability, a requested subject, a loaded record, and an
  action-determined permission are four different questions. Ownership-based
  checks decide from the **stored** record, never from request values, and each
  records a content-free witness so a route cannot be called enforced without
  runtime evidence the check ran.
- **A tenant-only action stays tenant-only on your own record.** `approve` /
  `reject` declare no self permission, so owning a memory does not let you approve
  it — self-approval would defeat the review queue that held it.
- **`GET /api/audit`** now resolves its subject through the shared helper; only
  the resolved tenant/user reach the repository.

### Behaviour changes
- **`PATCH /api/memories/{id}` with no changed field now returns 422** (was 200
  with the unchanged record). Such a body requests no action, so there is no
  permission it could be authorized against, and it wrote a governance loop run
  and a `memory_updated` audit event for a mutation that never happened. Refused
  before any evidence is written. `MemoryOpsClient.update_memory()` raises
  `ValueError` locally for the same case. No web caller sends an empty patch.
  This narrows a previously-accepted request shape, so it is a behavioural
  correction rather than an additive change; every patch that requests a real
  change is unaffected.

## Unreleased — the platform operational boundary

**31 of 40 routes enforced. Zero planned.** 9 public, each reviewed below.

### The distinction this draws
"Administrator of tenant A" and "operator of this deployment" are different
authorities. Three surfaces describe the *installation* rather than any tenant, and
now say so: `/api/traces` (a process-wide span buffer), `/api/evals/{latest,run}` (a
harness over its own fixtures and a process-wide result store), and the worker fleet.

- **`Role.PLATFORM_OPERATOR`** with `ops:evals:read`, `ops:evals:run`,
  `ops:traces:read`, `ops:metrics`, `ops:readiness` (plus `worker:read`). It holds no
  memory, audit, evidence, retention or consent permission — running the platform does
  not include reading what customers stored in it, and the two sets are asserted
  disjoint. Distinct from `service_worker`, which is the fleet's own identity.
- **No tenant role can reach an `ops:*` permission**, asserted for every one.
- `GET /api/traces` moves from `planned` to `enforced` as `Scope.OPERATOR` —
  classified for what it actually serves rather than redesigning tracing storage.
- `GET /api/loops/{runs,events,trace}` now use `audit:read:tenant`; both they and the
  audit trail answer "who acted in this tenant", and `traces:read:tenant` is retired.

### Fixed
- **`tenant_admin` was `frozenset(set(Permission))`** — every permission in the enum,
  including ones that did not exist yet. Any capability added anywhere became tenant
  authority by definition. The bundle is explicit, and a guard fails while any
  permission is neither granted nor recorded as deployment-scoped with a reason.

### Behaviour changes
- **`tenant_admin` no longer reads `/api/admin/workers/health`.** Fleet health is
  deployment state; it held that only through the blanket grant.
- **`auditor` and `tenant_admin` no longer read or run deployment evaluations.**
- **`/readyz` reports only `{ready, degraded, detail}` in production.** The detailed
  form named the storage backend, both providers, the embedding dimension, the profile
  and every dependency's state — an unauthenticated inventory of what the installation
  runs. The full report moved to `GET /api/admin/readiness` behind `ops:readiness`.
  Outside production the documented `1.x` shape is unchanged.
- **`/docs`, `/redoc` and `/openapi.json` are off in production** unless
  `MEMORYOPS_EXPOSE_API_DOCS=true`. The schema enumerates every route, parameter and
  model — a map of the attack surface, served unauthenticated.
- **`/metrics` can require `ops:metrics`** via `MEMORYOPS_PROTECT_METRICS_ENDPOINT`.
  Off by default, since most deployments scrape it privately. The auth middleware now
  authenticates that path when the switch is on — without a principal the route's
  check would silently no-op and the setting would look enforced while doing nothing.

## Unreleased — governance mutations enforced

**28 of 39 routes enforced.** Planned 2 (`POST /api/evals/run`, `GET /api/traces`),
public 9.

- **Legal hold, pin, protect and consent now require `retention:manage` /
  `consent:manage`.** `auditor` reads governance state and cannot change it;
  `memory_admin` and `tenant_admin` manage it within their tenant.

### Fixed
- **An admin could not govern another user's memory.** `_load()` ran
  `enforce_scope(request, tenant_id, user_id)` and then looked the record up with
  `repo.get_memory(tenant_id, user_id, memory_id)` — both halves trusting the
  request's `user_id`. Naming the real owner was refused (`403`, scope mismatch);
  naming yourself found nothing (`404`). The stored owner is now authoritative: the
  request's `user_id` is a compatibility hint about where to look, and the lookup is
  tenant-scoped and user-spanning.

### Audit evidence
- **Actor and target are recorded separately.** Once an admin can change someone
  else's governance state, `audit.user_id = "bob"` cannot say whether Bob acted or was
  acted upon. `user_id` stays the *target* for query compatibility, and content-free
  metadata now names `actor_id`, `actor_user_id`, `actor_type` (human /
  service_account), `target_user_id`, `authorized_permission`, and
  `acted_on_behalf_of_another_user`. Never the credential, its claims, or memory text.

## Unreleased — governance and evidence reads enforced

**24 of 39 routes enforced** (was 10). Planned 6, public 9.

- **Traces, evidence, retention and loop reads now require a permission.** The
  separation that matters: `memory_admin` can edit and delete anyone's memory in the
  tenant and **cannot** read the traces, evidence, or eval results that would show it.
  Reading the record of who acted is an auditor capability, not something memory
  management implies. Retention reads are the deliberate exception — describing what
  the system will forget is lifecycle management, so `memory_admin` holds
  `retention:read` too.
- **`require_authenticated`** implements the `authenticated` scope for the two static
  loop-definition routes, which need no capability. Borrowing an unrelated permission
  so the witness had one to record would have been a lie in the matrix. The
  definitions were inspected — and are now pinned by a test — as free of prompts,
  provider names, environment values, deployment detail, and tenant data.
- Authorization runs before any repository read, loop event, audit write, or
  computation. A refused read leaves no audit event, loop run, loop event, or row
  change — asserted per case, each with a positive control so the checks cannot pass
  vacuously.
- Every route forces the query to `principal.tenant_id` after authorizing; the
  request's own value is not reused.

### Behaviour changes
- **`GET /api/evals/latest` is now a pure read** and returns `404 no_result_available`
  when the process has completed no run. It previously regenerated whenever the cache
  was cold or older than `evals_cache_ttl_seconds`, so holding `evals:read` granted
  bounded but real *execution* authority — collapsing the `evals:read` / `evals:run`
  split those permissions exist to express. A TTL limits how often the work happens;
  it does not make the action a read. `POST /api/evals/run` is now the only request
  path that calls the harness, and it updates what `latest` serves. A stale result is
  still served (with `generated_at`) rather than regenerated, and a failed run does
  not replace the last known-good result.
  *These are deployment-wide results — the harness runs against its own isolated
  fixtures — not per-tenant evidence; the route takes no tenant parameter.*

### Deliberately still `planned`
- **`GET /api/traces`** is permission-gated (`traces:read:tenant`) as defence in
  depth, but stays `planned` because it is **not tenant-isolated**: the in-process
  span buffer has no tenant dimension, so a permitted caller observes the timing,
  volume and decisions of every tenant sharing the process. Spans carry no tenant id,
  user id or memory content, which limits the disclosure — but marking it `enforced`
  under a `:tenant` permission would claim a scope the runtime does not provide, which
  is the exact mismatch this route registry exists to prevent. Resolving it means
  either attaching a tenant to spans and filtering, or reclassifying the endpoint as
  deployment-level telemetry under a future `ops:traces` permission and operator role.
  A tenant auditor should not implicitly become a deployment-wide observability
  operator.

## Unreleased — governance read boundary

### Fixed
- **Loop evidence could be read across tenants on the in-memory backend.**
  `list_loop_runs` / `list_loop_events` filtered with `if tenant_id:`, so an empty
  string meant *no filter* and returned every tenant's loop runs — who did what,
  across the whole store. `tenant_id` is a plain `str` query parameter, so
  `GET /api/loops/runs?tenant_id=` reached the repository as `""`. The Postgres
  backend already refused this (`ValueError`), so the two backends disagreed about
  invariant #1. Both now fail closed identically. Reachable with authentication
  disabled, which is the development default and the playground's configuration.
- The eval harness listed loop runs unscoped, asking "did any write loop run
  *anywhere* in the store" — satisfiable by another case's runs. Now scoped to the
  case's tenant.
- Loop bookkeeping no longer raises when a run carries no tenant: the prior-state
  lookup is skipped instead, so evidence recording can never be the reason a request
  fails (invariant #4).

## Unreleased — memory routes enforced

Ten of 39 routes now enforce their declared permission (was three): `POST /api/chat`,
`GET /api/memories`, and the five `/api/memories/{id}` routes join `/api/audit`,
`/api/metrics` and `/healthz/workers`.

- **Ownership comes from the stored record.** Resource routes load the memory inside
  the authenticated tenant and decide from its stored owner — never from `tenant_id` /
  `user_id` in the request, which the caller controls. The supplied `user_id` stops
  being used at all once the record is loaded.
- **Authorization runs before side effects.** A refused request creates no loop run,
  no loop event, no audit event, no policy-broker call, no embedding, and no mutation.
  A correct status code is not the control if the evidence trail already records the
  attempt as a governance action that happened.
- **A mixed PATCH requires every applicable permission.** `{"content": …,
  "status": "active"}` is an edit *and* an approval; holding `memory:approve:tenant`
  no longer implies permission to rewrite the text being approved.
- **A mixed PATCH now leaves two audit records** (`memory_updated` + `memory_approved`)
  inside the same transaction, plus content-free `requested_actions` /
  `authorized_permissions` metadata. It previously collapsed to one record naming only
  the transition, so durable evidence said "approved" about a request that also
  rewrote the content.
- Self-approval remains impossible: the `approve` variant declares no self permission,
  so ownership cannot satisfy it.
- Legal hold still overrides a permitted delete (409), and that refusal is still
  audited — authorization decides whether a caller may *attempt* deletion, never
  whether a preservation control applies.

### Fixed
- **A JWT `roles` claim in array form was silently discarded.** `claim_path` rejects
  containers by design (a tenant or subject arriving as a list is malformed), but
  roles are normally a JSON array — so `["auditor"]` read as *no claim* and every
  JWT-authenticated caller fell back to `DEFAULT_ROLE`. An `auditor` token lost tenant
  audit access, and a token deliberately issued with `roles: []` received
  `memory_user` — read, write and delete over its own memory — for a credential the
  issuer said should carry none. Roles are now read with a new `claim_node`; scalar
  claims are unchanged. Trusted-header mode was never affected.
- **A JWT `roles` claim of explicit `null` was read as an omitted claim.** The array
  fix above left one state wrong: `claim_node` returned `None` for both an absent key
  and a JSON `null`, so `{"roles": null}` still took the compatibility fallback to
  `DEFAULT_ROLE`. Presence cannot be recovered from a value — the two are different
  statements (an issuer granting no roles, versus a credential predating roles), and
  only the second may fall back. `claim_node` now returns `(present, value)` and
  `resolve_roles` accepts an explicit `claim_present`. All six claim states are
  pinned: omitted → fallback; `null`, `[]`, `""`, unrecognised → zero permissions;
  valid → those roles. Identity claims are unchanged, where absent and `null` are
  correctly identical because there is no fallback to reach.

## Unreleased — worker mutation atomicity
Additive; completes invariant #7 across the whole system.

- **Background workers now commit mutation + audit atomically.** v2.3 made the
  API/governance write paths transactional but the lifecycle workers still mutated
  memory and then wrote the audit event as two separate commits. `LifecycleWorker._atomic`
  now wraps each worker's mutation and its audit evidence in one `repo.transaction(...)`
  — opened *before* the in-place mutation so the in-memory backend's rollback snapshot
  predates it. Covers decay, archive, retention (held + expired/consent soft-delete),
  and deletion-compaction (destructive content/vector clear + evidence);
  verification/conflict-scan/reflection are audit-only. Proven by
  `tests/test_worker_atomicity.py` (injected audit failure → neither the mutation nor
  its evidence survives). README/limitations/CLAUDE invariant #7 updated to reflect that
  the guarantee now holds on the worker paths too.

## v2.3 — Transactional Evidence + Production Guardrails (2026-07-26)
Additive under the `1.x` compatibility promise. Closes the gap between the
auditability *claim* and the transaction *boundary*, makes insecure defaults
fail-closed in production, and consolidates the operational + evidence hardening
that landed after the v2.2 tag.

### Transactional evidence
- **Atomic mutation + audit**: every mutation-plus-evidence path (save/update/merge,
  approve/reject/archive, manual edit, soft-delete + tombstone, legal-hold, pin,
  protect, consent) now runs inside a single `repo.transaction(...)` — a crash between
  the memory write and its audit event can no longer persist one without the other.
- **Fork-proof audit chain**: a tenant-locked `audit_chain_heads` table (migration 011)
  with `SELECT ... FOR UPDATE` serializes concurrent audited mutations onto one
  continuous hash chain (the in-memory backend uses an equivalent per-repo lock).
- **Worker-health regression fixed**: global worker health reads via an explicit
  cross-tenant *operational* connection (`OPERATIONAL_DATABASE_URL`, a monitoring role),
  fail-closed and clearly reported when unconfigured — never weakening tenant RLS.
- **Teeth**: `tests/test_transactional_evidence.py` proves rollback (neither side
  survives a partial failure) and chain continuity under 40 concurrent appends.

### Production guardrails
- **Production profile (fail-closed startup)**: `MEMORYOPS_PROFILE=production` makes
  the demo-friendly defaults hard startup errors — the API refuses to boot while the
  store is in-memory, auth is off, CORS is open (`*`), the DSN uses the bundled demo
  credentials, or the public-eval trigger is enabled. `MEMORYOPS_CORS_ALLOW_ORIGINS`
  now drives the real CORS allow-list. `dev` is unchanged. See
  `Settings.production_readiness_errors()` + `tests/test_production_profile.py`.
- **Dependency-specific readiness**: `GET /readyz` now reports per-dependency states
  (`storage`, `schema`, `vector_backend`, `worker_runtime`, `llm_provider`,
  `embedding_provider`) — each `ok`/`skipped`/`error` — instead of one combined
  detail string; `ready` is false iff a dependency is in `error`. All probes no-throw.

### Operational + evidence hardening
- **SDK published** to PyPI (`memoryops-sdk`) with a tag-only, version-locked
  publish workflow (`.github/workflows/publish-sdk.yml`).
- **Dependency security fixes**, including the PyJWT/`pyjwt[crypto]` path for the
  auth adapters and the Dependabot major bumps (web / RLS / perf) CI repairs.
- **Complete operational-evidence RLS** (migration 009): loop runs/events and worker
  runs now enforce the same `FORCE` tenant boundary as memory + audit rows.
- **Migration enforcement** at startup: the Postgres backend refuses to start unless
  the current schema migration is applied.
- **Real-model extraction evidence**: a live gemini-2.5-flash run
  (0.94 / 0.94 / 0.94, 0 fallbacks) recorded in `benchmark/EXTRACTION_QUALITY.md`,
  and the retired-model default fixed.
- **README consolidation** (550 → ~158 lines) and the empty-scope rejection fix.
- **Async decision recorded**: defer a blanket async conversion; tune and measure the
  synchronous path against real Postgres/provider workloads first
  (`docs/performance.md`, ADR).

## v2.2 — Public Benchmark + Examples
Additive under the `1.x` compatibility promise. Turns MemoryOps' *measured* governance
into a public, reproducible artifact. A new **benchmark** (`benchmark/run_benchmark.py`)
reuses the real eval harness (no new eval logic) and scores every case into named
governance suites — **deletion_and_leakage**, **tenant_isolation**, **context_admission**,
**policy_governance**, **retrieval_quality** — emitting a human scorecard/leaderboard, a
`--json` machine format, and a committed `benchmark/SCORECARD.md`. The **v2.2
release** benchmark was **32/32 (100%), critical suites perfect**; **current main**
is **50/50 (100%)** after the tenant-isolation and policy-governance suites were
expanded. The two **critical** suites (deletion/leakage +
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
