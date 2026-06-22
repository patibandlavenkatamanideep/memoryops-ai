# CLAUDE.md — MemoryOps AI working notes

> The authoritative product/architecture brief is [CLAUDE_ENTERPRISE.md](CLAUDE_ENTERPRISE.md).
> This file is the short operational guide for working in the repo.

## What this is

MemoryOps AI is a governed memory lifecycle system for AI assistants — not a chatbot with memory.
The lifecycle is: **Capture → Evaluate → Store → Retrieve → Rank → Compose → Update → Forget → Audit**,
wrapped by Security, Governance, Observability, Reliability, Evaluation planes.

> **v1.0 (stable).** The public HTTP API and Python SDK follow a `1.x`
> additive-compatibility promise — existing endpoints/methods keep their shape,
> responses only gain fields. A breaking change to that surface needs a MAJOR bump
> + deprecation window. See `docs/api-stability.md`, `docs/production-readiness.md`,
> `docs/limitations.md`, and `CHANGELOG.md`.

## Non-negotiable invariants (enforced in code + tests)

1. Tenant isolation — every memory query filters by `tenant_id` + `user_id`.
2. Deletion guarantee — `status='deleted'` rows are never retrieved.
3. Provenance — every memory has a non-null `source`.
4. Graceful degradation — retrieval failures never block responses.
5. Policy-before-storage — the policy broker runs before any write.
6. Temporary chat — `temporary_chat=true` writes/reads nothing.
7. Auditability — every lifecycle action appends an audit event.

## Layout

- `services/api` — FastAPI. Write path lives in `app/services/` (extractor, policy_broker,
  write_service) and is orchestrated by `app/services/gateway.py`. Read path:
  `app/services/{retriever,ranker,context_composer}.py`.
- `services/api/app/embeddings` — swappable `EmbeddingProvider` (stub default + optional OpenAI).
  `MEMORYOPS_EMBEDDING_PROVIDER=stub|openai`. `app/core/embeddings.py` is a back-compat shim.
- `services/api/app/compression` — optional context compression at the LLM boundary
  (`MEMORYOPS_CONTEXT_COMPRESSION=none|headroom`). `NoopCompressor` is the default;
  `HeadroomCompressor` is optional and degrades to no-op. Runs **after** policy/governance/
  composition, never before the policy broker. See ADR-007.
- `services/api/app/loops` — typed loop engineering layer (v0.3.1). Defines the six
  primary loops, validates state transitions, stores loop runs/events, and exposes
  `/api/loops` for operational timelines. Loop metadata must stay structured and safe:
  no raw secrets, API keys, or full user messages.
- `services/api/app/llm` — provider-neutral LLM layer (v0.4). Swappable `LLMProvider`
  (deterministic `StubProvider` default + optional OpenAI/Anthropic/Gemini adapters),
  schema-validated structured output, prompt registry, and heuristic fallback. Powers
  structured extraction + conflict detection. `MEMORYOPS_LLM_PROVIDER=stub|openai|anthropic|gemini`
  (default `stub`). LLM output is **advisory**: the policy broker stays authoritative
  and is never bypassed. Tests need no API keys. See ADR-008.
- `services/api/app/workers` — background memory lifecycle workers (v0.6–v0.7). Off
  the chat request path. Seven jobs: decay, archive, retention, deletion_compaction,
  deletion_verification, conflict_scan, reflection (retention + reflection off by
  default), driven by `runner.py`
  (`python -m app.workers.runner --tenant T --user U --job all`).
  Tenant scoped, idempotent, retry-safe, audited; never resurrect deleted memory;
  policy broker stays authoritative. `deletion_compaction` (v0.7) clears
  soft-deleted memory's content + vector material after a retention window,
  preserves the governance tombstone, and verifies the purge fail-closed (not
  crypto-shred / no physical disk reclamation claim). See ADR-010, ADR-011,
  `docs/background-lifecycle-workers.md`, `docs/deletion-compaction.md`,
  `docs/vector-purge-verification.md`.
  - v0.8 worker runtime: `orchestrator.py` + `scheduler.py` + `locks.py` (leases) +
    `retry.py` make the jobs operable — leased (duplicate runs prevented), retried
    with backoff, dead-lettered on exhausted retries, with persisted run history
    (`worker_runs`, migration 006) and a `GET /healthz/workers` view. Scopes are
    explicit (`worker_scopes`). `services/worker/main.py` runs the scheduler.
    See ADR-012 and `docs/worker-runtime.md`.
  - v0.10 retention layer: `app/services/retention.py` (policy packs: sensitivity
    tier → window) + `app/workers/retention.py` (`retention` job) soft-delete
    expired / consent-revoked memory (OFF by default). **Legal hold** (fail-closed)
    blocks all forgetting + the API delete route; consent withdrawal/expiry drives
    eligibility; pins/protection exempt. Governance state is metadata-driven
    (`app/db/governance.py`, migration 007), audited, and surfaced at
    `/api/retention/*` (`app/routes/retention.py`). Legal hold is a *preservation*
    control, not crypto-shred. See ADR-013, `docs/retention-policies.md`.
- `services/api/app/db` — repository abstraction. `MEMORYOPS_STORAGE=memory|postgres`. Vector
  retrieval goes through `Repository.search_candidates` (pgvector on Postgres, cosine in memory).
- `infra/db/migrations` — SQL schema (Postgres + pgvector). RLS is **enforced** in
  `004_rls_policies.sql` (`FORCE` + tenant policy); verify with `scripts/check_rls_policies.py`. See ADR-006.
- `apps/web` — Next.js frontend.
- `apps/results-dashboard` — read-only public Streamlit evidence dashboard (v0.9; demo-only).
- `apps/playground` — interactive public Streamlit playground (v0.12). Drives the
  **real** governed pipeline from `services/api` in-process against a fresh
  **in-memory** store per session (no DB, no secrets, no real data). Entrypoint is
  `streamlit_app.py` (named to avoid shadowing the `app` package). Demo-only — not
  the production UI; additive, no `services/api` changes. See `docs/playground.md`.
- `packages/memoryops-sdk` — typed Python SDK (v0.11) over the governed HTTP API
  (`MemoryOpsClient` injects the tenant/user scope on every call) + integration
  examples (quickstart, FastAPI, RAG, agent memory). Additive client only — the
  server stays authoritative for all governance; the SDK adds none. Tested against
  the real app in-process via an injectable `httpx.Client`. See ADR-014 and
  `docs/assistant-sdk.md`.
- `evals` — golden + adversarial cases, `run_evals.py`.

## Running

```bash
# API (no infra):
cd services/api && pip install -r requirements.txt && \
  MEMORYOPS_STORAGE=memory uvicorn app.main:app --reload

# Tests:
cd services/api && pip install -r requirements-dev.txt && pytest -q

# Full stack:
docker compose up --build
```

> **Deployment is Railway-only** (no Vercel) — one project, five services
> (web/api/worker + Postgres + Redis). Canonical docs live in
> `docs/deployment/railway.md`, `railway/`, and the phase gate
> `docs/phase-gates/phase-13-infrastructure.md`; `AGENTS.md` holds the
> operator-facing deployment workflow. (v0.3.2)

## Conventions

- New lifecycle actions MUST emit an audit event via `AuditService`.
- New retrieval paths MUST go through the repository's tenant-scoped methods.
- Keep the heuristic fallback working with no API keys; LLM adapters are optional enhancements.
- Phase status is tracked in `docs/rollout.md` and `docs/agentic-swe-kit-map.md`.
- Do NOT add AI co-author trailers to commits.

## Diagnostic (run before picking up work)

From agentic-swe-kit — answer these to route the work to the right phase gate:

1. New project, existing codebase, or live incident?
2. Any AI / LLM components involved?
3. Distributed or multi-service?
4. Auth or sensitive data in scope?
5. Which lifecycle phase is the project in? (see `docs/agentic-swe-kit-map.md`)

## Agentic Governance Integrations

Three agentic engineering integrations wrap the core. **They are not part of the
chat request path**; they make the project safer, more reviewable, and more
production-shaped. Overview: `docs/integrations/`.

1. **Hermes operator layer** — `.hermes/skills/{memoryops-architect,
   memoryops-release-manager,memoryops-invariant-auditor}/SKILL.md`. Operator/
   developer skills for architecture review, release checks, and invariant audits.
   Do not place Hermes in the API request path.

2. **agentic-swe-kit phase gates** — `docs/agentic-swe-kit-map.md` +
   `docs/phase-gates/`. Every major feature updates the relevant phase gate
   (0 Cognitive Design, 1 System Architecture, 5 LLM Reasoning, 6 Memory Architecture,
   9 Evaluation, 10 Observability, 11 Security, 12 Reliability, 15 Governance,
   18 CI/CD for AI, 20 Continuous Learning).

3. **PR Invariant Evidence Gate** — `scripts/pr_invariant_gate.py` +
   `.github/workflows/pr-invariant-evidence-gate.yml`, policy in
   `docs/ai-pr-review-policy.md`, roadmap in `docs/pr-review-agent-roadmap.md`.
   Deterministic (no LLM call); fails when memory/policy/retrieval/deletion/
   security/migrations/API-contract changes lack test/eval/doc/ADR evidence.
   Reviewer domains: Security, Memory Correctness, Evaluation, Docs/ADR.

   Run locally:
   ```bash
   python scripts/pr_invariant_gate.py --base HEAD~1 --head HEAD
   ```

4. **Loop engineering** — memory workflows are modeled as
   `Observe → Decide → Act → Verify → Audit → Learn` loops. See
   `docs/loop-engineering.md`, `docs/loop-contracts.md`, and `docs/release-loop.md`.
