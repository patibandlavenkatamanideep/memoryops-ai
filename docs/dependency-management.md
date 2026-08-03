# Dependency management & provider packaging

`services/api/pyproject.toml` is the **single source of truth** for API and worker
dependencies. Every `services/api/requirements*.txt` is generated from it and
verified in CI.

## Why

The API had two independent dependency sources that had silently diverged:

| Package | `pyproject.toml` | `requirements.txt` |
| --- | --- | --- |
| fastapi | 0.139.2 | 0.140.0 |
| uvicorn | 0.37.0 | 0.51.0 |
| pydantic-settings | 2.6.1 | 2.14.2 |
| pytest-recording | *(absent)* | 0.13.2 |

Docker images and CI install the requirements files; `pip install .` and the
published wheel resolve the pyproject set. A green CI run therefore proved nothing
about the package metadata, and nothing about the image once the two drifted.

## Workflow

```bash
# 1. Edit dependencies in services/api/pyproject.toml (never a requirements file)
# 2. Regenerate
python scripts/sync_dependencies.py
# 3. Commit both pyproject.toml and the regenerated requirements files
```

CI (`packaging` job) runs `python scripts/sync_dependencies.py --check` and fails on
drift. `tests/test_packaging.py` runs the same check locally.

Generated files (all carry a DO-NOT-EDIT banner):

| File | Contents | Used by |
| --- | --- | --- |
| `requirements.txt` | `[project].dependencies` | base install, SDK CI |
| `requirements-postgres.txt` | `postgres` extra | Postgres CI |
| `requirements-providers.txt` | `providers` extra | nightly live-provider smoke |
| `requirements-production.txt` | `production` extra | API + worker images |
| `requirements-dev.txt` | `dev` extra + `-r requirements.txt` | tests, lint |

## Dependabot targets the manifest, never the mirrors

Only **authoritative** manifests are watched:

| Watched | Why |
| --- | --- |
| `/services/api` | `pyproject.toml` is the source of truth |
| `/packages/memoryops-sdk` | declares its own dependencies |
| `/apps/web` | `package.json` |
| `/` (github-actions) | workflow pins |

`services/worker`, `apps/playground` and `apps/results-dashboard` are **not**
watched. Their requirements files are `-r` includes:

```
services/worker/requirements.txt   ->  -r ../api/requirements.txt
apps/playground/requirements.txt   ->  -r ../../services/api/requirements.txt  (+ streamlit)
```

Dependabot resolves those includes, so it opened PRs *labelled* for the worker or
playground that in fact edited `services/api/requirements.txt` — a generated file.
Those edits are erased by the next `scripts/sync_dependencies.py` run and fail the
drift gate, so they could never merge. Four were closed (#104, #105, #107, #108).

Upgrades reach those directories by changing `services/api/pyproject.toml` and
regenerating.

### Grouped by blast radius

A single `patterns: ["*"]` group produced one PR bundling FastAPI, Uvicorn,
SQLAlchemy, psycopg, pgvector, pytest, Ruff and setuptools (#109, closed). A red
result would not say which upgrade caused it; a green one would not say the others
were exercised. Groups are now `api-runtime`, `database` and `provider-sdks`.

**pgvector, pytest and Ruff are excluded** from automatic proposals — they change
behaviour, not just versions: vector semantics, test collection, and a lint rule set
that can fail CI on untouched code. Upgrade them deliberately, one PR each.

## Optional extras

```bash
pip install 'memoryops-api[openai]'      # LLM + embeddings via OpenAI
pip install 'memoryops-api[anthropic]'
pip install 'memoryops-api[gemini]'
pip install 'memoryops-api[providers]'   # all three
pip install 'memoryops-api[qdrant]'      # or [lancedb] / [weaviate]
pip install 'memoryops-api[production]'  # postgres + all providers (what the images install)
```

Every provider adapter imports its SDK **lazily**, so the package stays importable
and the test suite stays fully offline without any of these. That laziness is also
how the SDKs went missing from every runtime image: selecting
`MEMORYOPS_LLM_PROVIDER=openai` in an image without `openai` installed silently
degraded to the deterministic stub, with only a log line to show for it.

> The `gemini` extra pins **`google-generativeai`** (module `google.generativeai`),
> the legacy SDK that `app/llm/gemini_provider.py` actually imports — *not* the newer
> `google-genai` (module `google.genai`). Migrating the adapter is tracked follow-up
> work and needs a live-key test to land safely. `test_provider_extras_pin_the_module_each_adapter_imports`
> pins this correspondence so an extra can never install an SDK its adapter cannot use.

### Fail-closed under `MEMORYOPS_PROFILE=production`

`Settings.production_readiness_errors()` now refuses to start when a networked
provider is selected but cannot actually be used:

- `llm_provider` set to `openai`/`anthropic`/`gemini` with no API key, or with the
  SDK missing.
- `embeddings_provider='openai'` with no key or SDK.
- `vector_index` set to an external backend whose client is not installed.

Dev keeps degrading silently — offline tests and the demo depend on it.

## Embedding-space integrity

The OpenAI embedding adapter used to catch provider errors and return
`StubEmbeddingProvider` output in their place. That reads like graceful degradation
(invariant #4) but is a silent correctness bug: the stub vector lives in a
**different embedding space** from the model's, yet is indistinguishable from a real
one once persisted. A transient outage permanently poisoned the index with vectors
whose distances are meaningless — no signal, and no way to identify affected rows.

Invariant #4 requires that a failure never *blocks the response*. It does not
license fabricating data. The adapter now raises `EmbeddingUnavailable`, and the
existing call sites degrade correctly:

- `write_service` wraps it in `safe_call(..., default=[])` → the memory is stored
  with **no vector** and ranks by keyword only; it can be re-embedded later.
- `retriever` catches it and returns `mode="fallback"` (keyword-only retrieval).

Covered by `tests/test_embedding_integrity.py`.

> Not yet implemented: an async re-embedding worker, and per-vector
> `provider`/`model`/`dimension`/`embedding_version` columns to make un-embedded and
> stale-space rows queryable. Both are follow-up work — the change above stops new
> contamination, it does not backfill or label existing vectors.

## Packaging

The wheel must carry everything the app reads at runtime. `app/llm/prompts/*.md` are
loaded from disk by `app/llm/prompt_registry.py`; with no `package-data` declared
they were **omitted from the wheel**, so every structured-intelligence call raised
`PromptNotFoundError` in a wheel-installed deployment while passing in dev and CI
(where the source checkout supplies the files).

`[tool.setuptools.package-data]` now declares them, and two guards keep it that way:

- `tests/test_packaging.py::test_every_runtime_asset_dir_is_declared_as_package_data`
  fails when any new non-`.py` file appears under `app/` without a matching
  `package-data` entry.
- The `packaging` CI job builds the wheel, installs it into a clean venv, `cd`s out
  of the source tree, and boots it — so a missing packaged file cannot be masked by
  the checkout.

## Node

`apps/web/Dockerfile` uses `npm ci` only. The previous `npm ci || npm install`
fallback defeated the lockfile: a stale or absent `package-lock.json` silently
regenerated the dependency tree, so the image could ship versions no one reviewed
and CI never saw. The lockfile is also now copied non-optionally
(`package-lock.json`, not `package-lock.json*`), so a missing lock fails the build.
