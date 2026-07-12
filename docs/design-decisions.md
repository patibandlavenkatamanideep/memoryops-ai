# Design decisions — MemoryOps AI

> A record of the hardest calls in this codebase: the decision, the alternative that
> was rejected, and why. It's meant to be quizzed. (Personalize the voice — the
> reasoning below is factual and matches the code, ADRs, tests, and CHANGELOG.)

## 1. The policy broker is authoritative; the LLM is advisory

**Decision.** A memory only becomes state after the deterministic policy broker runs
(`app/services/policy_broker.py`), *before* any write. LLM extraction/conflict output
is a suggestion the broker can override; it is never on the trust path.

**Rejected.** Letting the model decide what to store. That couples correctness and
governance to a nondeterministic component and makes "why was this stored?"
unanswerable.

**Why.** Governance must be explainable and testable with no API key. Every invariant
(block secrets, tenant isolation, deletion) is provable deterministically because the
authority is deterministic. The model only makes the system *smarter*, never *less safe*.

## 2. Deletion is tombstone + compaction + leakage evals, not crypto-shred

**Decision.** Delete = soft-delete (status + `deleted_at`), a preserved governance
tombstone, later content/vector compaction, and — crucially — *leakage evals* that
probe whether a deleted memory can still influence output (directly, via summaries,
via lineage, cross-session, or after reindex). Tombstone lineage denies any memory
whose ancestry contains a deleted node.

**Rejected.** Claiming "crypto-shred / hard delete." We can't honestly promise physical
disk reclamation across Postgres/pgvector, so we don't.

**Why.** The valuable, testable guarantee is *"deleted memory never influences an
answer,"* not a storage claim we can't back. The eval battery makes the guarantee
*measurable* and release-gating instead of aspirational.

## 3. The stub is the default; real providers are optional — and the gap is published

**Decision.** The default LLM + embeddings are deterministic stubs. Real providers
(OpenAI/Anthropic/Gemini) are opt-in. Extraction *quality* is measured separately, per
provider, in a published precision/recall scorecard, and real-provider behavior is
pinned in CI via recorded (VCR) cassettes.

**Rejected.** Making a real provider the default (tests need keys, CI is flaky/costly,
"does it work?" is unfalsifiable offline) — or hiding the stub's weakness.

**Why.** Offline determinism keeps the whole suite runnable with no secrets, and
publishing the stub's honest gap (high precision, lower recall + multi-memory) turns
the benchmark from self-graded marketing into an instrument. The stub is documented as
a *test fixture, not the product*.

## 4. Tenant/user are opaque strings with no FKs; RLS is defense-in-depth

**Decision.** `tenant_id`/`user_id` are opaque text everywhere — the app never
provisions `tenants`/`users` rows, and the memory tables have no FK to them. Postgres
Row-Level Security is a *second* wall behind app-level scoping, enforced with `FORCE`
and verified by a **non-superuser** role (superusers bypass RLS even with FORCE).

**Rejected.** UUID scope columns with FKs to a tenants table (the original schema).
That made the Postgres write path unusable with the string ids the app actually uses,
and would have required a user-management surface the product doesn't own.

**Why.** MemoryOps verifies an *externally minted* identity; it isn't an auth product.
Opaque string scope matches that and the in-memory backend, so both backends behave
identically. (Migration 008 reconciled the original uuid schema to this; the RLS tests
were rewritten to prove isolation through a non-privileged role, which is the only way
the guarantee is real.)

## 5. Invariants are enforced by tests, not discipline

**Decision.** Scope is checked centrally by middleware for query-string routes and
by `enforce_scope` in body routes — and a **meta-test** introspects every mutating
`/api/*` route and fails if a body-scoped one forgets to enforce. Same spirit for the
leakage/isolation benchmark suites, which are release-gating.

**Rejected.** Trusting reviewers to remember. That already failed once — `PATCH`/
`DELETE /api/memories/{id}` shipped taking scope from the body without enforcing it (a
cross-tenant vector, now fixed and guarded by the meta-test).

**Why.** "Every query is tenant-scoped" is the product's thesis; a thesis should be
machine-checked, so a new route can't silently break it.

## 6. Dependency-free where cheap; a real library where crypto is involved

**Decision.** Metrics, tracing, and rate limiting are dependency-free in-process
implementations (they fit the single-instance deploy and add no supply chain). JWT
verification, by contrast, uses **PyJWT** (+ JWKS), not hand-rolled token crypto.

**Rejected.** Both extremes — pulling a framework for a counter, *and* hand-rolling
JWT signature parsing.

**Why.** Small, well-understood utilities are cheaper and clearer in-house; token
crypto is not — JWTs have a long history of subtle parser CVEs, so "dependency-free"
there is a liability, not a feature.

## 7. Sync-first, honestly — with the blocking hot path called out

**Decision.** The request path is currently synchronous. Where a real bottleneck
exists it is documented, not hidden (see [limitations.md](limitations.md)), including
the fact that the memory write and its audit event commit in **separate transactions**
today (a partial-failure gap surfaced by the chaos tests).

**Rejected.** Claiming "async, production-grade throughput" without a load test, or
papering over the write/audit atomicity gap.

**Why.** An honest limitation with a remediation path (async conversion; a repository
unit-of-work) is worth more than an unverified claim. These are the next scoped
efforts, tracked deliberately rather than rushed.
