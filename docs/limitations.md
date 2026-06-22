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
- No built-in end-user **authentication/authorization** layer ships in v1.0 — the
  API trusts the `tenant_id`/`user_id` scope the caller provides; deploy it behind
  your own auth. See [security.md](security.md).

## Models & retrieval

- The default **LLM and embedding providers are deterministic offline stubs** (no
  API key). Optional OpenAI/Anthropic/Gemini adapters exist; quality with stubs is
  intentionally reproducible, not production-grade generation.
- LLM output is **advisory** — the deterministic policy broker stays authoritative
  and is never bypassed.
- Retrieval is hybrid (vector + keyword) with graceful degradation to keyword-only
  on embedding failure; ranking is heuristic, not a learned ranker.

## Observability & operations

- Structured logs, audit events, worker run history, and `GET /healthz/workers`
  ship; full **OpenTelemetry traces / Prometheus metrics / Langfuse** wiring is on
  the production roadmap, not in the box.
- Workers run on a thin lease/scheduler runtime, not Celery/Temporal; there is no
  external queue/broker.

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
