# API & SDK Stability — MemoryOps AI (v1.0)

As of **v1.0**, the public HTTP API and the Python SDK surface are **stable**:
within the `1.x` line they are additive-compatible. This document is the contract
for what "stable" means and how changes are governed.

## Two version tracks

MemoryOps AI intentionally versions on two separate axes. They answer different
questions and move independently, so a single number would be misleading:

| Track | Where it lives | Current | Meaning |
|-------|----------------|---------|---------|
| **Platform release** | git tags `vX.Y`, the README release badge, `CHANGELOG.md` | **v2.2** | "What shipped" — the feature-set milestone of the whole repo (API + workers + SDK + docs + demos). |
| **Public API + SDK contract** | `app.__version__`, `packages/memoryops-sdk` `version` | **1.0.0** | The compatibility promise of the public HTTP API and Python SDK. Stays `1.x` as long as the surface is additive-compatible. |

So platform **v2.2** ships the **1.0.0** API/SDK contract: the milestone counter has
advanced through many feature phases while the *public surface* has only grown
additively and so remains `1.x`. `app.__version__` and the SDK package version are
kept in lock-step; the platform milestone is independent.

## Versioning

- Platform releases are git tags `vMAJOR.MINOR[.PATCH]` (see
  [RELEASING.md](../RELEASING.md)); the tag + GitHub Release are the source of truth
  for "what shipped".
- The API/SDK contract version (`app.__version__`, `packages/memoryops-sdk`) is
  **1.0.0** and is released to PyPI under `sdk-vX.Y.Z` tags. CI asserts an `sdk-v*`
  tag matches the SDK's `pyproject.toml` version (see `.github/workflows/publish-sdk.yml`).
- Within `1.x`: **MINOR** adds backward-compatible capability, **PATCH** is
  fixes/hardening. A breaking change to the stable surface requires a **MAJOR**
  bump (`2.0`) and a deprecation window.

## Stable HTTP surface

Canonical request/response shapes live in [api-contracts.md](api-contracts.md)
(kept in sync by the PR Invariant Evidence Gate). Stable endpoints:

| Area | Endpoints |
|------|-----------|
| Chat | `POST /api/chat` |
| Memories | `GET /api/memories`, `GET /api/memories/{id}`, `PATCH /api/memories/{id}`, `DELETE /api/memories/{id}`, `GET /api/memories/{id}/audit`, `GET /api/memories/{id}/provenance` |
| Retention / governance | `POST /api/retention/{legal-hold,pin,protect,consent}`, `GET /api/retention/{policies,decisions}`, `GET /api/retention/memory/{id}` |
| Audit & metrics | `GET /api/audit`, `GET /api/metrics` |
| Loops | `GET /api/loops`, `/api/loops/runs`, `/api/loops/events`, `/api/loops/trace/{id}`, `/api/loops/{id}` |
| Health | `GET /healthz`, `GET /healthz/workers`, `GET /readyz` |

**Compatibility promise (1.x):** existing endpoints keep their methods, paths, and
required request fields; responses only **gain** fields. New fields may appear on
any response, so clients must ignore unknown fields (the SDK does — see below).

## Stable SDK surface

`MemoryOpsClient` ([packages/memoryops-sdk](../packages/memoryops-sdk)) is the
stable client. Stable methods: `chat`, `list_memories`, `get_memory`,
`update_memory`, `delete_memory`, `memory_audit`, `memory_provenance`,
`set_legal_hold`, `pin`, `protect`, `set_consent`, `retention_policies`,
`retention_decisions`, `memory_governance`, `audit`, `metrics`, `loops`,
`loop_trace`, `health`, `workers_health`.

Stable client guarantees:

- **Scope injection** — `tenant_id`/`user_id` are attached to every call.
- **Forward compatibility** — response models keep `.raw`, so new server fields are
  never lost and never break parsing.
- **Typed errors** — `LegalHoldError` (409), `NotFoundError` (404), `APIError`
  (other), all subclasses of `MemoryOpsError`.

## What is explicitly NOT covered by the stability promise

- Internal modules under `services/api/app/**` (services, workers, repositories) —
  implementation detail; import at your own risk.
- The demo surfaces (`apps/results-dashboard`, `apps/playground`) — demo-only.
- Provider adapters' generation *quality* (stub vs OpenAI/Anthropic/Gemini).
- Anything listed in [limitations.md](limitations.md).

## Deprecation policy

A stable endpoint/method is removed or changed incompatibly only across a MAJOR
bump, after at least one MINOR release where it is documented as deprecated (and,
for the SDK, emits a `DeprecationWarning`). Audit-event action names are treated as
a stable vocabulary on the same terms.
