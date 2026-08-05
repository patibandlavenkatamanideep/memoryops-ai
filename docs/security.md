# Security — MemoryOps AI

Security is a cross-cutting plane, not a feature. This document describes the controls implemented in
Phase 0/1 and the production hardening roadmap.

## Threat model

The most dangerous failures for an AI memory system are:

1. **Cross-tenant / cross-user leakage** — A's memory surfaced to B.
2. **Secret capture** — API keys, passwords, tokens persisted as "memory".
3. **Deletion failure** — a "forgotten" memory still influencing answers.
4. **Silent sensitive storage** — health/financial/identity data stored without consent.
5. **Memory poisoning** — low-utility or adversarial content polluting retrieval.

## Controls implemented (Phase 1)

### Tenant & user isolation (invariant #1)
- Every repository method requires `tenant_id` and `user_id` and filters on them.
- No endpoint returns memory across tenants. Verified by `tests/test_tenant_isolation.py`.
- **Database-level Row-Level Security is enforced (v0.3).** Migration
  `004_rls_policies.sql` applies `FORCE ROW LEVEL SECURITY` plus a tenant-isolation
  policy (`tenant_id::text = current_setting('app.tenant_id', true)`) to
  `memory_records`, `memory_audit_logs`, `memory_feedback`, and `memory_settings`.
  The Postgres repository sets the transaction-local `app.tenant_id` GUC on every
  session, so even a bug in application-level filtering cannot leak across tenants
  (defense in depth). RLS is tenant-scoped; per-user isolation stays in application
  SQL so tenant-wide admin/metrics reads still work.
- Verified by `tests/test_rls.py` (DB-guarded; skips without Postgres) and
  `scripts/check_rls_policies.py`. See [ADR-006](../infra/adr/ADR-006-pgvector-rls-retrieval.md).

### Embeddings & retrieval (v0.3)
- Embeddings come from a swappable `EmbeddingProvider`. The default stub is
  deterministic and offline; the optional OpenAI provider activates only when
  `OPENAI_API_KEY` is set and degrades to the stub on failure — no key is ever
  required to run, and a flaky embeddings API never blocks the read path.
- Vector candidate fetch (`search_candidates`) is tenant+user scoped and excludes
  `deleted`/non-active rows at the source, so deleted and wrong-tenant memories are
  never retrievable.

### Pluggable vector backend (v1.7)
- Similarity search flows through a swappable `VectorIndex` (`app/db/vector/`) so
  MemoryOps runs on Qdrant / LanceDB / Weaviate / pgvector without moving governance
  into the vector store. The index holds **ids + embeddings only** — never content,
  provenance, consent, or lineage — and the authoritative `Repository` plus the
  admission gate re-check every candidate id it returns, so a stale index entry can
  never leak content (defense-in-depth).
- Every backend must uphold a written contract, proven by
  `assert_vector_index_contract`: `query(tenant, user, …)` returns only that scope's
  vectors (isolation, #1); `delete`/soft-delete/compaction remove the vector so a
  deleted memory can never resurface as a candidate (deletion, #2); an unreachable
  backend returns no matches and degrades to keyword-only rather than failing (#4).
  Deletion compaction now also clears the memory's vector material via the index.

### Policy-before-storage (invariant #5)
- The Policy Broker runs before the Write Service. Nothing reaches the store unevaluated.

### Secret / PII detection
- Regex + heuristic detectors for: OpenAI-style keys (`sk-...`), AWS keys (`AKIA...`), bearer/JWT
  tokens, generic `api_key=`, passwords, credit-card-like and SSN-like numbers, emails/phones.
- Secret-like content → `BLOCK` (never stored). Identity/contact PII → elevated `sensitivity`.
- See [services/api/app/core/redaction.py](../services/api/app/core/redaction.py).

### Sensitivity & approval
- `sensitivity ∈ {low, medium, high}`. With `require_approval_for_sensitive=true`, sensitive
  memories are stored as `pending` and excluded from retrieval until approved.

### Deletion guarantee (invariant #2)
- `DELETE` is a soft delete: `status='deleted'`, `deleted_at=now()`, plus an audit event.
- Retrieval excludes non-active statuses, so deleted memory can never be retrieved again.

### Tombstone lineage — deletion propagation to derived artifacts (v1.4)
- Deletion also stamps an explicit, audited **tombstone** marker
  (`metadata.lineage.tombstoned`) so the guarantee propagates to *derived*
  artifacts (summaries/consolidations), not just the source row — closing the
  *"not retrievable ≠ cannot influence output"* gap.
- The Context Admission Gate blocks any memory whose lineage ancestry contains a
  tombstoned/deleted/**purged-or-unknown** ancestor (`BLOCK_TOMBSTONED_ANCESTOR`),
  fail-closed and transitive. Ancestry is resolved through a **tenant/user-scoped**
  lookup, so a cross-tenant parent id reads as missing and is blocked (no
  cross-tenant ancestry resolution).
- Proven by `test_deletion.py`, `test_deletion_proof_lineage.py`,
  `test_tenant_isolation.py`, and the `leakage` / `derived_tombstone` eval cases.
  See [deletion-proof-lineage.md](deletion-proof-lineage.md),
  [ADR-018](../infra/adr/ADR-018-tombstone-lineage-deletion-proof.md).

### Temporary chat (invariant #6)
- `temporary_chat=true` short-circuits both read and write — no candidates extracted, none stored,
  none retrieved. Audit records `temporary_chat_skipped`.

### Audit immutability (invariant #7)
- `memory_audit_logs` is append-only by convention (no update/delete endpoints). In production this
  is enforced with a revoked-UPDATE/DELETE grant and/or WORM storage.
- **Tamper-evident hash chain (v2.0, ADR-024).** Each audit event links to the previous
  one in its **tenant's** chain (`entry_hash = SHA-256(canonical(event) + prev_hash)`),
  set centrally in `repo.add_audit`. `verify_chain` reconstructs order from the links and
  detects any edit, deletion, insertion, or reorder — surfaced at
  `GET /api/evidence/audit/verify` and folded into every evidence report
  (`chain_intact`). The chain is per-tenant (no cross-tenant linkage; invariant #1) and
  covers deletion/compaction audit events too, so a deletion proof is verifiable. This is
  tamper-*evidence*, not tamper-*proofing* — pin the head hash to a WORM store/notary for
  a stronger guarantee. See [enterprise-evidence.md](enterprise-evidence.md).
- **Atomic mutation + audit (v2.3, ADR-027).** Every mutation-plus-evidence path
  (save/update/merge, approve/reject/archive, manual edit, soft-delete + tombstone,
  legal-hold/pin/protect/consent) runs inside one `repo.transaction()`, so a crash
  between the memory write and its audit event can no longer persist one without the
  other — the auditability guarantee holds under partial failure, not just the happy path.
- **Fork-proof chain under concurrency (v2.3, ADR-027).** A per-tenant `audit_chain_heads`
  row (migration 011) is locked with `SELECT ... FOR UPDATE` while a new event links and
  advances the head, so concurrent audited mutations serialize onto one continuous chain
  instead of forking it. The in-memory backend uses an equivalent per-repo lock.
- **Operational health never weakens RLS (v2.3, ADR-027).** Global (cross-tenant) worker
  health reads through a *separately authorized* operational connection
  (`OPERATIONAL_DATABASE_URL`), never the request-scoped RLS engine; unconfigured, it
  fails closed to a documented "not configured" state rather than leaking or crashing.

### Loop engineering traces (v0.3.1)
- `loop_runs` / `loop_events` (migration `005_loop_engineering.sql`) store operational lifecycle
  traces tagged with `tenant_id` / `user_id`; `Repository.list_loop_runs` filters by that scope so
  traces never leak across tenants (`test_tenant_isolation.py`).
- Loop metadata is structured and bounded — **no raw secrets, API keys, or full user messages** are
  recorded, only state transitions, reasons, and counts.
- Loop traces are operational evidence, not a retrieval surface: they never re-expose a
  soft-deleted memory (`test_deletion.py::test_loop_traces_do_not_resurrect_deleted_memory`).

### Memory control plane (v0.5)
- The browser control plane is a **read + audited-action** surface only; it never
  writes around the policy/write path, and the policy broker stays authoritative.
- New read routes (`GET /api/memories/{id}`, `/{id}/provenance`, `/{id}/audit`) and
  the `list_audit(memory_id=…)` filter are all tenant + user scoped at the
  repository (`test_tenant_isolation.py`, `test_governance_api.py`).
- Provenance responses are metadata only — no embeddings, keys, or secrets are
  serialized.
- Detail may return a soft-deleted row for forensics, but it always carries
  `status=deleted`; it is never listed as active or rendered as active
  (`test_deletion.py`, `test_governance_api.py`).
- Identity **verification** and scope enforcement ship as off-by-default auth
  adapters (`MEMORYOPS_AUTH_MODE=none|trusted_header|jwt`): a JWT/JWKS or trusted-
  header adapter verifies an externally-minted identity and enforces that every op is
  scoped to the authenticated tenant/user (401/403, never 500). See
  [auth-adapters.md](auth-adapters.md), ADR-020. The demo identity
  (`tenant_demo`/`user_demo`) in `apps/web/lib/api.ts` is the `none`-mode default;
  identity **issuance** (session/SSO) and **RBAC** remain on the hardening roadmap below.

### Background lifecycle workers (v0.6)
- Workers (`services/api/app/workers/`) run **off the chat path** and are tenant +
  user scoped: each run operates on a single explicit `(tenant_id, user_id)` via
  the repository's scoped methods, so a worker cannot reach another tenant's
  memory (`test_*_worker.py`, `test_lifecycle_worker.py`).
- Workers **never resurrect or modify deleted memory**: mutating jobs read active
  rows only and re-filter `status != deleted`; the deletion verification worker is
  read-only (`test_decay_worker.py`, `test_archive_worker.py`,
  `test_deletion_verification_worker.py`).
- **Deletion verification** continuously confirms soft-deleted memory is absent
  from active retrieval, default listing, and the vector candidate path, recording
  pass/fail evidence (invariant #2). This verifies **logical** forgetting — see
  [deletion-verification.md](deletion-verification.md).
- A worker failure can never block chat: exceptions are caught and recorded as
  `lifecycle_worker_failed`, never raised into a caller (invariant #4).
- Worker audit metadata is content-free (ids / counts / flags only). Reflection is
  proposal-only and **disabled by default**.

### Deletion compaction + vector purge verification (v0.7)
- The **deletion compaction worker** clears a soft-deleted memory's `content`,
  normalized content, embedding/vector material, and provenance excerpt after a
  retention window, while preserving the governance tombstone (id, tenant/user,
  `status='deleted'`, `deleted_at`, `source.kind`) and the full audit trail
  (`test_deletion_compaction_worker.py`, `test_deletion.py`).
- Only `status='deleted'` rows are ever compacted; active/archived memory is never
  touched and deleted memory is never resurrected/reactivated (invariants #1, #2).
- The purge is **verified fail-closed**: a still-reachable id, intact material, a
  missing tombstone, or a verification-path error all record
  `memory_vector_purge_failed` and flag the run — never a silent pass
  (`test_vector_purge_verification.py`).
- Every step is audited content-free: `deletion_compaction_started/completed/
  failed/skipped`, `memory_content_compacted`, `memory_vector_purge_attempted/
  verified/failed`, `memory_purge_tombstone_preserved`.
- **Honest boundary.** v0.7 is auditable content/vector compaction +
  retrieval-exclusion verification at the application + repository level. It is
  **not** crypto-shred, does **not** guarantee physical disk/database-page byte
  erasure, and does **not** orchestrate pgvector reindex/`VACUUM`. See
  [deletion-compaction.md](deletion-compaction.md),
  [vector-purge-verification.md](vector-purge-verification.md), and
  [ADR-011](../infra/adr/ADR-011-physical-deletion-compaction-vector-purge.md).

### Worker runtime (v0.8)
- The scheduled worker runtime persists two new operational artifacts —
  **leases** (`worker_leases`) and **run history** (`worker_runs`, migration
  `006`). Both are **content-free**: run records carry ids, counts, status,
  attempts, and owner only — never memory content (`test_deletion.py::
  test_worker_runtime_preserves_deletion_guarantee`).
- Run history is **tenant scoped** at the repository (`list_worker_runs`
  filters by `tenant_id`/`user_id`; `test_tenant_isolation.py::
  test_worker_runs_are_tenant_scoped`). Lease keys are scope identifiers
  (`"tenant:user"`), not data.
- A **lease prevents duplicate concurrent runs** of a scope across replicas and
  **expires**, so a crashed worker never deadlocks a scope. Exhausted retries are
  **dead-lettered** (never silently lost) and surfaced at `GET /healthz/workers`.
- The runtime stays **off the chat path** and never resurrects deleted memory —
  running it over a scope preserves the deletion guarantee. See
  [worker-runtime.md](worker-runtime.md) and
  [ADR-012](../infra/adr/ADR-012-worker-runtime-orchestration.md).

## Authorization decisions are centralized (v2.4)

Authentication answers *who are you*. Authorization answers *may you do this on
this record*, and until v2.4 each route answered it in its own way — which is how
`GET /api/audit` came to return tenant-wide rows to any authenticated caller.

### The route contract

`app/auth/authz_spec.py` states, for every route, its **scope**, the permission it
requires, and whether that requirement is `enforced` or still `planned`:

| Scope | Meaning |
| --- | --- |
| `public` | no credential (health, readiness) |
| `authenticated` | any verified principal |
| `self` | acts only on the caller |
| `subject` | resolves a *requested* subject; no stored record exists to inspect |
| `tenant` | tenant-wide data; needs a `:tenant` permission |
| `resource` | loads a stored record first, then decides from its owner |
| `operator` | operational surface, not memory content |

A route added without a spec fails the build, and
[security/endpoint-authorization-matrix.md](security/endpoint-authorization-matrix.md)
is **generated** from the spec — the published matrix cannot drift from the code.

`planned` is stated deliberately. A route listed as enforced that is not would be
worse than an unlisted one, because the matrix is what a reader trusts.

### The four helpers

`app/auth/decisions.py` — separate helpers, not one with optional arguments. A fixed
capability, a requested subject, a loaded record, and an action-determined permission
are four different questions; one signature covering all four makes every call site
look plausible while doing something subtly different.

- `require_permission` — a fixed capability.
- `authorize_subject_scope` — resolves which subject may be queried and **forces the
  query to it**. The returned tenant/user are the only values that may reach the
  repository; echoing back the caller's values after validating them leaves untrusted
  input in the query path, which is not authorization.
- `authorize_loaded_resource` — decides from the **stored** record's owner. Never from
  `tenant_id` / `user_id` in the body, which the caller controls.
- `authorize_transition` — picks the permission from the action the server already
  validated, never from a client-supplied action string. An action the route never
  declared fails closed (500) rather than falling back to a route-level permission.

### Two rules that are easy to get wrong

**Ownership does not grant a tenant-only action.** `approve` and `reject` declare no
self permission, so owning a memory does not let you approve it — self-approval
defeats the review queue that held it. A missing self branch means *tenant-only*, not
*own record, therefore allowed*.

**Concealment over refusal.** A cross-tenant record, or another user's record you may
not touch, answers `404`, not `403`. A `403` confirms the record exists, which is
itself a disclosure — an attacker can enumerate ids by status code alone.

### Enforcement evidence

Each helper records a content-free **witness** (`app/auth/witness.py`): the route, the
helper, the permission, the action, and whether the check was tenant-scoped. A pinned
list of enforced routes is only a claim; the witness is runtime evidence that a check
actually ran, so a handler that silently stopped checking — and would still return the
right answer for an authorized caller — is detectable.

### Cross-tenant lookup for ownership

Deciding ownership needs the record *before* the owner is known, so it cannot filter
by `user_id`. `Repository.get_memory_in_tenant(tenant_id, memory_id)` provides this
with the tenant as a **predicate in the query** — not a global lookup by id with the
tenant compared afterward, which is one dropped condition away from a cross-tenant
read while reading as safe because the comparison is right there. RLS
(`004_rls_policies.sql`) remains the outer guarantee; neither layer is alone
load-bearing.

It deliberately returns soft-deleted rows, so the deletion guarantee is re-proved
against it in `tests/test_deletion.py`: the lookup is not a retrieval path, and
nothing downstream re-enters retrieval or context.

### Enforcement order (v2.4)

Authorization is not only *whether* a check runs but *when*. Every enforced route
authorizes before it does anything observable:

```
reject a request that asks for nothing        (422, no lookup — not an id oracle)
load the record inside the authenticated tenant
404 if absent
validate the lifecycle transition
derive every action the body requests
authorize every one of them
open the governance loop run
policy broker / legal hold / compare-and-swap
atomic mutation + audit
```

A refused request must leave **no** loop run, loop event, audit event, policy-broker
call, embedding, or row change. Otherwise the refusal came too late: the evidence
trail records an action nobody was permitted to take, and the expensive work ran on
the caller's schedule. This is asserted per refusal case, with a companion test
proving the counters move on a real request so the checks cannot pass vacuously.

Legal hold sits *after* authorization and is unaffected by it. Authorization decides
whether a caller may **attempt** a deletion; a hold decides whether deletion may
happen at all. A tenant admin holding every delete permission is still refused with
409 — and that refusal *is* audited, because a permitted action stopped by a
preservation control is exactly what evidence is for.

### The resource lookup

Resource routes load the memory with `get_memory_in_tenant(principal.tenant_id, id)`
and authorize against its **stored** owner. Two consequences worth stating:

- The request's `user_id` stops being used once the record is loaded. It was only ever
  a hint about which record to find; continuing to pass it would put caller-controlled
  input back into queries authorization has already settled, and would silently return
  nothing when an admin legitimately reads another user's memory.
- The authenticated tenant is always part of the lookup, so a memory in another tenant
  is *not found* rather than *refused*.

### Provider parity

Authorization depends on the resolved `Principal`, never on how it arrived. Trusted-
header and JWT modes are asserted to produce identical decisions for the same roles,
including role resolution. This test found a real divergence: a JWT `roles` claim in
array form — the shape almost every issuer emits — was discarded, so every JWT caller
fell back to the default role.

Role claims have **six** states, and only the first may fall back:

| Claim | Result |
| --- | --- |
| omitted | `DEFAULT_ROLE` where the deployment permits it (`auth_require_role_claim`) |
| `null` | zero permissions |
| `[]` | zero permissions |
| `""` | zero permissions |
| `["unrecognised"]` | zero permissions |
| `["auditor"]` | those roles |

The distinction that makes this work is that **presence is not inferred from the
value**. An absent key and a JSON `null` both read as `None`, but they are opposite
statements: an issuer saying *this identity has no roles*, versus a credential that
predates roles entirely. `claim_node` therefore returns `(present, value)`. Collapsing
them is what let an explicit `null` keep receiving the fallback even after array
claims were fixed.

Identity claims (`tenant_id`, `sub`) are the opposite case: absent and `null` are
correctly identical, because there is no fallback to reach — both refuse
authentication rather than invent an identifier.

See the v2.4 entries in `CHANGELOG.md`.

### Governance evidence is tenant-scoped in the query

Loop runs, loop events and audit rows record *who did what, when*. They carry no
memory content, but the trail itself is tenant-confidential, so every read puts the
tenant in the query rather than filtering afterwards:

| Read | Scoping |
| --- | --- |
| loop runs / events | `WHERE tenant_id = :tenant`, and a missing tenant raises |
| audit rows | `WHERE tenant_id = :tenant` (+ optional user / memory) |
| evidence deletion, lifecycle | `repo.get_memory(tenant, user, id)` |
| retention governance view | `repo.get_memory(tenant, user, id)` |
| evidence bundle by `trace_id` | tenant-scoped audit read, then filtered by trace |

An opaque identifier is **not** an authorization token. `loop_run_id`, `trace_id` and
`memory_id` are all unguessable, and none of them is allowed to stand in for scope — a
leaked or brute-forced id still returns nothing outside its tenant.

The in-memory backend previously filtered loop evidence with `if tenant_id:`, so an
empty string meant *no filter* and returned every tenant's runs. Because `tenant_id`
is a plain `str` query parameter, `?tenant_id=` reached it as `""`. Postgres already
refused this, so the two backends disagreed about invariant #1 — the kind of gap that
only shows up when both are tested against the same assertion. Both now fail closed.

#### Why some evidence reads answer 200 with no data

`GET /api/evidence/deletion/{memory_id}` returns `200` with `found: false` rather than
`404` when the memory is not in scope. That is deliberate: a deletion proof has to be
answerable for a memory that no longer exists, which is the case it exists *for*. A
`404` would fail on exactly the memories that were most thoroughly forgotten, making
"prove this is gone" unanswerable. It discloses nothing, because the lookup is
tenant-scoped and "absent" covers never-existed, hard-purged, and belongs-to-another-
tenant without distinguishing them.

Record-shaped governance views that are *not* proofs — `GET /api/retention/memory/{id}`
— still answer `404`.

### What is not claimed

This is an authorization boundary, not an authorization product. Roles are coarse
named bundles, not per-record ACLs; there is no delegation, no attribute-based policy,
and no per-field redaction by role. Route statuses are moving from `planned` to
`enforced` incrementally — **10 of 39 today** — so read the generated matrix for the
current state rather than assuming the whole surface is covered.

Two limits specific to the memory routes:

- `GET /api/memories` is effectively self-only. Its `user_id` is a required query
  parameter and the scope middleware pins query-string scope to the principal, so the
  tenant branch of the subject helper is not reachable there: an admin lists another
  user's memories one record at a time, by id. The tenant branch is kept because the
  helper is shared, and is exercised by `/api/audit`.
- `GET /api/memories/{id}` still returns soft-deleted records for governance and
  forensics. This is deliberate and unchanged — authorization visibility is not
  retrieval visibility, and the row carries its true `status`. Every retrieval path
  still excludes it (invariant #2), which is re-proved against the new lookup.

## Production hardening roadmap

- Encryption at rest (pgcrypto / disk) + field-level encryption for high-sensitivity content.
- KMS-managed keys with rotation.
- SSO/SAML + SCIM provisioning.
- Full RBAC (user / approver / admin / auditor) and per-role API scopes.
- Data export (DSAR), right-to-be-forgotten workflow (retention/legal hold landed in v0.10).
- Regional data residency.
- Deploy with a restricted (non-owner) DB role in addition to `FORCE RLS` for layered enforcement.
- SOC 2 control mapping (access, change management, audit logging, encryption).
- Rate limiting + abuse detection on the gateway.

## Retention, legal hold & consent (v0.10)

The retention layer (ADR-013, [retention-policies.md](retention-policies.md)) adds
compliance controls over the deletion pipeline. Governance state — legal hold,
consent, pins, protection, and the computed retention window — is metadata-driven
(like the v0.7 compaction tombstone) and round-trips on both repository backends;
`postgres_repo.update_memory` was fixed to persist `extra_metadata` so this state
(and the v0.6 lifecycle markers) survive updates. Migration
`007_retention_legal_hold_consent.sql` adds partial indexes for "on hold" /
"consent withdrawn" lookups.

Security-relevant properties:

- **Legal hold is fail-closed and preservation-oriented.** A held memory cannot be
  decayed, archived, retention-deleted, or compacted, and the API delete route
  refuses it (HTTP 409, audited). Hold *retains* content for discovery — it is
  **not** crypto-shred and makes no physical-erasure claim.
- **Consent withdrawal is honored.** Withdrawn/expired consent makes a memory
  eligible for the normal soft-delete → verification → compaction path; it never
  bypasses the deletion guarantee.
- **Retention only ever makes the system more conservative.** The engine decides
  eligibility; the policy broker stays authoritative and is never bypassed
  (invariant #5). All mutations are tenant-scoped (invariant #1) and audited
  (invariant #7). Retention auto-deletion is **OFF by default**.

## Content edits are a governed write path

`PATCH /api/memories/{id}` previously assigned edited content straight onto the
stored row. The policy broker — the choke point invariant #5 requires before *any*
write — ran on creation and not on editing, so the edit path was a way around every
control that creation enforces:

| Control | Bypassed how |
| --- | --- |
| Secret scanning | Content that creation BLOCKs (API keys, tokens, private keys) could be introduced by editing an innocuous memory |
| Prompt-injection guard | Same — an injection payload could be edited in |
| Sensitivity classification | Sensitivity was **inherited** from the stored row, not recomputed, so an edit into PII kept a `low` label and approval gating, recall-gate audience clearance, and the admission gate all stopped applying |
| Legal hold | Ignored entirely; a hold preserves content, and editing destroys it as effectively as deleting |
| Embedding integrity | The vector was never touched, so the row kept the embedding of its *previous* content — dense retrieval matched the old text and returned the new text |

On Postgres this was worse: `update_memory` never persisted `normalized_content` or
`embedding` at all, so both stayed stale permanently once content changed.

Edits now run through `app/services/update_service.py`:
legal hold → revision check → policy evaluation on the **proposed** content →
apply → invalidate and regenerate the embedding → bump revision → audit.

Refusals are fail-closed and leave the stored memory byte-identical: `422` for a
secret or injection, `409` under legal hold or on a stale `expected_revision`, `404`
for a deleted memory. A sensitive edit is applied but returns the memory to
`pending`.

**Audit evidence is content-free.** The event records `previous_content_hash` /
`new_content_hash`, the before/after sensitivity, the decision, the revision, and a
`policy_version` — never the before/after text. The audit trail is read by operators
who may not be cleared for the memory itself, and a deleted memory's content must
not survive in its audit events.

**Known gap.** Sensitivity classification still only matches *structural* patterns
(SSN, card numbers, key formats). An edit into `my password is hunter2`, a medical
diagnosis, or salary information is not yet detected, so those still classify `low`.
The governed path is now in place to enforce whatever the classifier decides —
expanding the classifier is separate, tracked work.

## Optimistic concurrency

Memories carry a `revision` (migration 012), incremented by the repository on
**every** mutation — content edits, governance transitions, retention and consent
changes, and lifecycle worker jobs. That makes it a genuine row revision and one
shared concurrency contract, rather than a content-only counter.

A caller may send `expected_revision` on a content edit and receives `409 Conflict`
if the memory changed underneath, instead of silently overwriting a concurrent
change. Omitting it preserves last-write-wins.

The guard is enforced **in the write**, not before it: `update_memory_checked`
issues `UPDATE ... WHERE revision = :expected` and treats `rowcount == 0` as the
conflict. An application-side `if revision == expected` would be a
time-of-check/time-of-use race — two requests can both read revision N, both pass,
and both write — and embedding generation sits between the read and the write,
widening the window considerably.

The 409 is raised **after** tenant scoping, so it is not a cross-tenant oracle: a
request for another tenant's memory returns `404` whether or not the revision would
have matched.

## Production rejects governance ablation

The research-ablation switches (`MEMORYOPS_GOVERNANCE_PROFILE=disabled`,
`MEMORYOPS_ABLATE_*`) exist so the paper study can measure a governed system against
a mechanism-matched ungoverned twin. They ship in the same binary as production, and
nothing stopped them being combined with `MEMORYOPS_PROFILE=production`.

Verified before this guard existed: a **fully hardened** production config —
Postgres, JWT auth, explicit CORS allow-list, real DSN, evals off — plus
`MEMORYOPS_GOVERNANCE_PROFILE=disabled` produced **no** readiness errors, and a live
API key was stored with `status=active`. The policy broker's BLOCK never ran. Every
one of the seven invariants could be disabled by an environment variable while the
deployment reported itself production-ready.

`Settings.production_readiness_errors()` now rejects, under the production profile:

| Setting | What breaks |
| --- | --- |
| `governance_profile != full` | the ablation cascade below |
| `govern_policy_enforcement=false` | the broker does not run before storage (invariant #5) |
| `govern_transactional_evidence=false` | mutations and audit events stop committing atomically (invariant #7) |
| `govern_tombstone_propagation=false` | deletion stops propagating to derived memories (invariant #2) |
| `admission_gate_enabled=false` | nothing is checked for admissibility before entering context |
| `recall_gate_enabled=false` | audience clearance is not enforced on recall |
| `output_gate_enabled=false` | answers are not checked for disclosure of blocked memory |
| any `MEMORYOPS_ABLATE_*` present | any value flips its control off, so presence is disqualifying |

All seven default to enabled, so this rejects only deployments that explicitly
turned governance off. Dev is unchanged, so the paper study still runs.

**This is the guard, not the cure.** The stronger fix is architectural: ship the
ablation wiring in a separate `memoryops-research` package or application factory so
a production binary cannot express these states at all. Tracked separately.
## Sensitivity classification

`app/core/sensitivity.py` performs **deterministic semantic-pattern and structural
sensitivity classification**. It is not medical, financial, or credential
*understanding*: there is no ontology, no model, and no inference beyond the rules
written in that module.

### What it replaced

Classification matched only *structural* patterns — SSN and card digit shapes,
API-key formats. Semantic disclosures scored `low` and were stored `active`:

| Content | Before | After |
| --- | --- | --- |
| `my password is hunter2` | low / active | **blocked, not stored** |
| `my HIV status is positive` | low / active | high / pending approval |
| `I take sertraline for depression` | low / active | high / pending approval |
| `my salary is $250,000` | low / active | high / pending approval |

Every downstream control keys off sensitivity — approval gating, the recall gate's
audience clearance, the admission gate — so for exactly the categories those
controls exist to protect, they were inert. A plaintext password was retrievable
into a `public`-audience response.

### Three separate responsibilities

1. **Detection** — rules emit `SensitivityFinding(category, rule_id, sensitivity,
   recommended_disposition, confidence)`. Content-free: a finding names *what*
   matched, never the value.
2. **Aggregation** — `SensitivityAssessment` applies deterministic precedence:
   `BLOCK > PENDING_APPROVAL > SAVE`, `high > medium > low`.
3. **Policy** — the broker decides, applying tenant settings, approval
   configuration, the governance profile, consent, and temporary-chat behaviour on
   top. The classifier recommends; it never stores or refuses. This keeps the
   scanner from becoming a second policy broker.

### Category policy

| Category | Recommended |
| --- | --- |
| Password / passcode / PIN / security answer | BLOCK |
| Recovery code, backup code, seed phrase | BLOCK |
| API key, token, private key (structural) | BLOCK |
| Payment card / bank account / routing number | BLOCK |
| Government identifier (SSN, passport, licence) | BLOCK |
| Medical: diagnosis, condition, status | high + approval |
| Mental health: condition, psychiatric medication | high + approval |
| Financial condition: salary, debt, balance | high + approval |
| Precise private location: home address | high + approval |
| Biometric: fingerprint, face template, voiceprint | high + approval |
| Ordinary preference | low + save |

### A keyword is not a disclosure

Rules require first-person ownership **and** a disclosure verb **and** a value or
condition, plus a framing guard for questions and educational text. These must not
classify as sensitive, and are permanent test cases:

```
I forgot my password                          I use a password manager
How should password hashing work?             Sertraline is a commonly prescribed medication
I am reading research about HIV               What is the average software engineer salary?
This document explains bank routing numbers
```

### Memory-control instructions store nothing

`do not remember my password`, `forget my salary`, `I don't want you to remember my
address` are instructions *about* memory, not facts. The correct outcome is **no
persistent memory** — not a stored high-sensitivity record (which would be the same
disclosure by another route) and not merely a `BLOCK` verdict.

Two independent guards: the extractor emits no candidate, and the policy broker
refuses one anyway, so a malformed or LLM-provided extractor cannot store it.

### Both write paths agree

Every positive case is tested through creation **and** through an existing-memory
content edit. The same content must reach the same classification and disposition
regardless of how it enters the system — the equivalence the edit path used to
break.

### Audit evidence

Only `sensitivity_categories`, `sensitivity_rule_ids`, `sensitivity_finding_count`,
the final sensitivity and disposition, and the policy version. Never the matched
password, diagnosis, salary, address, or regex excerpt.

### Policy change: government identifiers

`policy_version = content-update-v1`, classifier rules as of this change.

Government identifiers (SSN, passport, driving licence) moved from
**approval-gated** to **non-storable (BLOCK)**. Previously `my ssn is …` matched the
structural SSN pattern, scored `medium`, and was stored `pending` awaiting approval;
it is now refused outright on both the creation and edit paths. Operators who relied
on approving such records will see them rejected instead of queued.

### Classification is clause-scoped

Framing guards and memory-control detection apply per clause, not per message.
Whole-message checks let one clause exempt another:

```
"I am reading research about HIV. My HIV status is positive."      -> was: no findings
"What is the average software engineer salary? My salary is $250,000."  -> was: no findings
"Do not remember my password, but remember that I prefer dark mode."    -> was: stored nothing
```

The educational clause now exempts only itself, and only the memory-control clause
is stripped before extraction — the unrelated preference survives.

`forget my X` is distinguished from `do not remember my X`: the first is a request
to remove *existing* memory, the second only prevents new persistence. Both suppress
a new candidate. Routing the first into the governed forget workflow (legal hold,
`deleted_at`, tombstone, lineage, deletion audit) is follow-up work and deliberately
not done here — deleting on a chat phrase would be a destructive action taken
outside the deletion path's guarantees.

### Rows stored before the classifier existed

Classification runs at write time, so a row already stored `low`/`active` keeps its
label — the protection would otherwise apply only to content entering after deploy.
A pre-existing credential row was verified to still reach a `public`-audience
response with its full source excerpt.

The read path therefore combines the stored label with a current classification and
uses whichever is **higher** (`app/services/effective_sensitivity.py`). It only ever
raises: an operator's explicit `high` is never lowered because the rules happen not
to match.

This is deliberately **not** a write. Reads must not mutate rows — that would turn
every query into a write, produce audit events with no actor, and race with
concurrent edits. Persisting the corrected label with audit evidence belongs to a
reclassification worker.

A memory withheld for audience clearance now returns **no content preview and no
source excerpt** in the trace; echoing them would disclose exactly what the gate
withheld.

### Memory-control drops are distinguishable

A memory-control instruction is dropped with `reason_code=memory_control_instruction`,
distinct from a genuine `low_utility` drop. "Not a memory at all" and "a valid memory
of low utility" are different outcomes, and conflating them would skew utility
metrics and error analysis. A dedicated decision value
(`IGNORE_MEMORY_CONTROL` / `DROP_NOT_MEMORY`) is the right long-term shape and is
tracked separately; the reason code keeps the vocabulary additive meanwhile.

### Limits, stated plainly

Pattern rules miss paraphrase, other languages, obfuscation, and unusual phrasing.
**A rule that fires is high-confidence; silence is not evidence of safety.**
Broadening recall belongs with evaluation evidence, not with more unreviewed
regexes. This is not comprehensive medical, financial, or credential understanding.
