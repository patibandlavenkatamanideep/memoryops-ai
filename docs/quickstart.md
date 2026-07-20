# Quickstart — full local setup

The [README](../README.md) has the 30-second SDK path. This is the complete local
setup: running the API with and without infrastructure, embeddings, LLM adapters, the
frontend, and enforced Row-Level Security.

## Option A — API only, no infra (fastest)

The API ships with an in-memory repository, so the write path and tests run without
Postgres.

```bash
cd services/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export MEMORYOPS_STORAGE=memory          # default; uses in-memory store
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000/docs
```

Run the invariant test suite:

```bash
cd services/api
pip install -r requirements-dev.txt
pytest -q
```

Run the eval harness (against a running API or in-process):

```bash
cd evals && python run_evals.py
```

## Option B — Full stack with Docker Compose

```bash
cp .env.example .env
docker compose up --build
# web  → http://localhost:3000
# api  → http://localhost:8000/docs
# db   → localhost:5432 (postgres/pgvector)
# redis→ localhost:6379
```

Compose runs migrations from `infra/db/migrations` on first boot and sets
`MEMORYOPS_STORAGE=postgres` for the API.

## Embeddings

Retrieval uses a swappable embedding provider. The default is a deterministic, offline
stub — no API key — so tests and demos are reproducible.

```bash
export MEMORYOPS_EMBEDDING_PROVIDER=stub     # default; deterministic, no key
# optional real embeddings:
export MEMORYOPS_EMBEDDING_PROVIDER=openai
export OPENAI_API_KEY=sk-...
export OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

An unconfigured or failing provider degrades to the stub, and a query-embedding failure
degrades retrieval to keyword-only (`retrieval_mode="fallback"`).

## LLM provider adapters

Extraction and conflict detection run through a provider-neutral LLM layer
(`app/llm/`). The default is a deterministic, offline stub — no API key — so behavior is
reproducible and tests never touch the network. Optional OpenAI, Anthropic, and Gemini
adapters are used only when their key is set.

```bash
export MEMORYOPS_LLM_PROVIDER=stub          # default; deterministic, no key
# optional real providers (used only when the key is present):
export MEMORYOPS_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=...   ANTHROPIC_MODEL=claude-haiku-4-5-20251001
# also: openai (OPENAI_API_KEY/OPENAI_MODEL), gemini (GEMINI_API_KEY/GEMINI_MODEL)
export MEMORYOPS_LLM_FALLBACK_TO_HEURISTIC=true   # invalid JSON / failure → heuristic
```

LLM output is advisory: the deterministic policy broker runs after extraction and stays
authoritative — a model can never override policy, and secret-like content is still
blocked. See [provider-llm-adapters.md](provider-llm-adapters.md),
[structured-memory-intelligence.md](structured-memory-intelligence.md), and
[ADR-008](../infra/adr/ADR-008-provider-llm-adapters.md).

## Enforced Row-Level Security

Verify FORCEd Postgres RLS against a running database:

```bash
python scripts/check_rls_policies.py        # SKIPs cleanly if no DB is reachable
```

## Frontend

```bash
cd apps/web
npm ci
npm run dev          # http://localhost:3000
```

The frontend reads `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

## Repository layout

```text
memoryops-ai/
  apps/web/            Next.js frontend (chat, memories, governance, audit, loops, admin)
  apps/results-dashboard/ Read-only Streamlit evidence dashboard (demo-only; v0.9)
  apps/playground/     Interactive Streamlit playground over the real pipeline (demo-only; v0.12)
  services/api/        FastAPI backend (gateway, extractor, policy broker, write/read path, audit)
  services/worker/     Background jobs (decay, reflection, conflict resolution, compression)
  packages/memoryops-sdk/ Python SDK 1.0.0 + integration examples
  infra/db/            Postgres + pgvector migrations and seed
  infra/adr/           Architecture Decision Records
  evals/               Golden + adversarial cases and the eval runner
  benchmark/           Public governance benchmark + scorecard
```
