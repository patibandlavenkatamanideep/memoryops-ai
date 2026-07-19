# Known Limitations — MemoryOps AI (v1.0)

The single, authoritative list of what MemoryOps **does not** claim. Stating these
plainly is part of the product: a governed memory system earns trust by being
honest about its boundaries. Individual feature docs link here rather than
re-deriving their own caveats.

## Deletion & forgetting

- **Not crypto-shred.** Deletion compaction clears retrievable content + vector
  material and preserves a governance tombstone; it does **not** perform
  cryptographic erasure of keys.
- **No physical disk/page-erasure guarantee.** Compaction is an application- and
  repository-level clear, not a guarantee that database pages or ANN-index bytes
  are physically overwritten/reclaimed.
- **No pgvector VACUUM / reindex orchestration yet.** Vector material is cleared
  and verified unreachable, but index compaction/reclamation is not orchestrated.
- **Legal hold is a *preservation* control, not shred.** It blocks forgetting
  (decay, archive, retention, deletion, compaction) fail-closed; it is not a
  compliance certification.
- Honest scope of what deletion *does* guarantee: retrieval exclusion, repository
  content/vector clearing where supported, deletion verification, compaction,
  vector purge verification, tombstone preservation, and audit evidence. See
  [deletion-compaction.md](deletion-compaction.md) and
  [vector-purge-verification.md](vector-purge-verification.md).

## Retention, legal hold & consent

- Retention auto-deletion is **OFF by default** and per-tenant/user scoped; there
  is no cross-tenant retention scheduler yet.
- **Consent is captured/edited via the API/SDK, not yet at a first-class UI edge**
  for end users; the worker acts on the conservative outcome only.
- Retention/legal-hold/consent are governance metadata + workers, not a legal
  compliance product. See [retention-policies.md](retention-policies.md).

## Storage, security & isolation

- **RLS is enforced** on Postgres (`FORCE` + tenant policy), but **field-level
  encryption** for high-sensitivity rows is not implemented.
- Tenant isolation is enforced in code + tests on every scoped read; the
  in-memory backend mirrors the Postgres semantics but is for dev/demo only.
- **Authentication/authorization adapters ship but are off by default.** With
  `MEMORYOPS_AUTH_MODE=none` (the default) the API trusts the caller-supplied
  `tenant_id`/`user_id` scope, so you must front it with your own auth. Set
  `trusted_header` or `jwt` to have MemoryOps verify an externally-minted identity
  (JWT/JWKS via PyJWT, or a trusted upstream header) and enforce tenant/user scope.
  MemoryOps verifies identity and enforces scope; it does not *issue* identity — that
  stays with your IdP. See [auth-adapters.md](auth-adapters.md), [security.md](security.md).
- **Dependency scanning is clean and unignored.** `pip-audit` (in `security-scan.yml`)
  runs as a blocking gate with **no `--ignore-vuln` allowlist**. The earlier
  `starlette` advisories (transitive via `fastapi==0.118.0`) were resolved by upgrading
  to `fastapi==0.139.2` + a pinned `starlette==1.3.1`, not accepted as debt.

## Models & retrieval

- The default **LLM and embedding providers are deterministic offline stubs** (no
  API key). Optional OpenAI/Anthropic/Gemini adapters exist; quality with stubs is
  intentionally reproducible, not production-grade generation.
- LLM output is **advisory** — the deterministic policy broker stays authoritative
  and is never bypassed.
- Retrieval is hybrid (vector + keyword) with graceful degradation to keyword-only
  on embedding failure; ranking is heuristic, not a learned ranker.

## Observability & operations

- Structured logs, audit events, worker run history, `GET /healthz/workers`,
  **Prometheus metrics** (`GET /metrics`, content-free + low-cardinality — ADR-015),
  and **distributed tracing** (span façade with an optional OpenTelemetry bridge,
  spans at `GET /api/traces`; `MEMORYOPS_TRACING_ENABLED` / `MEMORYOPS_OTEL_ENABLED` —
  ADR-022) all ship. Deeper wiring (an exporter/collector deployment, dashboards,
  **Langfuse** LLM-trace integration) is left to the operator, not in the box.
- Workers run on a thin lease/scheduler runtime, not Celery/Temporal; there is no
  external queue/broker.
- **Write + audit are not yet a single transaction.** On the Postgres backend the
  memory write (`create_memory`) and its audit event (`add_audit`) commit separately,
  so a process crash *between* them could leave a stored memory without its audit row
  (an invariant #7 gap under partial failure — surfaced by `tests/test_chaos.py`). The
  happy path always audits; the fix is a repository unit-of-work that spans both
  writes, tracked for a future release. Retrieval/degradation and the deletion
  guarantee are already proven under injected failure (`tests/test_chaos.py`).

## Demo surfaces

- The **results dashboard** (`apps/results-dashboard`, v0.9) is **read-only and
  static** — demo JSON, not a live view. See [results-dashboard.md](results-dashboard.md).
- The **playground** (`apps/playground`, v0.12) is **interactive but demo-only**:
  in-memory, ephemeral, per-session, no DB/secrets/real data. See
  [playground.md](playground.md).
- Both are evidence/demo surfaces. The **Next.js app (`apps/web`) is the official
  product / governance UI.**

## Deployment

- Deployment is **Railway-only** (no Vercel): one project, five core services
  (web/api/worker + Postgres + Redis). The demo surfaces are optional and are not
  part of the five. See [deployment/railway.md](deployment/railway.md).

---

For the complementary "what *is* guaranteed" view, see
[production-readiness.md](production-readiness.md) and the enforced invariants in
[architecture.md](architecture.md).
