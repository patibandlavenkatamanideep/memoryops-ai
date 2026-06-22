# AGENTS.md — MemoryOps AI working notes

> The authoritative product/architecture brief is [CLAUDE_ENTERPRISE.md](CLAUDE_ENTERPRISE.md).
> This file is the short operational guide for working in the repo.

## What this is

MemoryOps AI is a governed memory lifecycle system for AI assistants — not a chatbot with memory.
The lifecycle is: **Capture → Evaluate → Store → Retrieve → Rank → Compose → Update → Forget → Audit**,
wrapped by Security, Governance, Observability, Reliability, Evaluation planes.

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
- `services/api/app/llm` — provider-neutral LLM layer (v0.4). Swappable `LLMProvider`
  (`StubProvider` default + optional OpenAI/Anthropic/Gemini), schema-validated structured
  output, prompt registry, heuristic fallback. `MEMORYOPS_LLM_PROVIDER=stub|openai|anthropic|gemini`
  (default `stub`). Powers structured extraction + conflict detection. LLM output is
  **advisory** — the policy broker stays authoritative and is never bypassed; tests need
  no API keys. See ADR-008.
- `services/api/app/db` — repository abstraction. `MEMORYOPS_STORAGE=memory|postgres`. Vector
  retrieval goes through `Repository.search_candidates` (pgvector on Postgres, cosine in memory).
- `infra/db/migrations` — SQL schema (Postgres + pgvector). RLS is **enforced** in
  `004_rls_policies.sql` (`FORCE` + tenant policy); verify with `scripts/check_rls_policies.py`. See ADR-006.
- `apps/web` — Next.js frontend. v0.5 adds the **memory control plane**:
  `/memories`, `/memories/[id]`, `/governance`, `/audit`, with reusable components
  under `components/{memories,governance,audit}`. It is a read + audited-action
  surface only — every action maps 1:1 to an audited backend route and never
  writes around the policy broker. Backend additions are read-only
  (`GET /api/memories/{id}`, `/{id}/provenance`, `/{id}/audit`) plus a `memory_id`
  filter on `list_audit`/`/api/audit`. See ADR-009,
  `docs/governance-ui.md`, `docs/memory-control-plane.md`.
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

## Deployment workflow (Railway-only — v0.3.2)

Deployment target is **Railway only**. Do **not** add or suggest a Vercel path.
One project (`memoryops-ai`), five services: `memoryops-web`, `memoryops-api`,
`memoryops-worker`, Railway Postgres (+pgvector), Railway Redis.

- Config-as-code lives in `railway/{api,web,worker}.railway.json`; point each
  Railway service at its file. Builder is `DOCKERFILE`.
- Per-service Root Directory: api → `services/api`, web → `apps/web`, worker →
  repo root. Full settings + deploy order: `docs/deployment/railway.md`.
- Env var contract per service: `docs/deployment/railway-env.md`. The system runs
  with **no provider keys** (heuristic LLM + stub embeddings); set
  `MEMORYOPS_STORAGE=postgres`, `DATABASE_URL`, `REDIS_URL` for production, and
  build-time `NEXT_PUBLIC_API_URL` for web.
- After deploy, run `scripts/railway_smoke_test.py` (see
  `docs/deployment/railway-smoke-test.md`).
- When changing deployment, update `railway/`, the three `docs/deployment/*`
  files, and `docs/phase-gates/phase-13-infrastructure.md` together.

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
   (0 Cognitive Design, 1 System Architecture, 6 Memory Architecture, 9 Evaluation,
   10 Observability, 11 Security, 12 Reliability, 15 Governance, 18 CI/CD for AI,
   20 Continuous Learning).

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
