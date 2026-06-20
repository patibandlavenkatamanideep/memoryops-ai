# MemoryOps AI — Invariant Evidence Gate Policy

Status: **v0.1 CI-only evidence gate**

MemoryOps AI runs a PR Invariant Evidence Gate for repository changes. It is a
GitHub/CI workflow only: it detects changes to security- and governance-sensitive
surfaces, runs the deterministic test + eval suite, and posts an advisory evidence
checklist on the PR. It is not part of the memory runtime, does not decide policy,
and does not mutate code. The gate is fully deterministic and makes no LLM call —
the name stays honest rather than labeling it "AI".

The design principle matches the rest of the project:

> Deterministic tests and evals are the source of truth and are enforced (the
> workflow fails when required checks fail). The posted checklist is advisory and
> helps reviewers notice risk and missing evidence.

Reference project: [ayush488-glitch/ai-pr-review-agent](https://github.com/ayush488-glitch/ai-pr-review-agent)
— a full webhook service with specialist LLM review sub-agents. MemoryOps keeps
v0.1 narrower: a deterministic, repo-local invariant gate that can later be wired
to that agent (or an optional LLM diff reviewer) without changing the memory
runtime.

## Sensitive surfaces

The gate flags changes to:

| Surface | Path | Why it matters |
|---|---|---|
| Policy broker | `services/api/app/services/policy_broker.py` | Policy-before-storage (#5) |
| Redaction / secrets | `services/api/app/core/redaction.py` | Secret/PII/injection detection |
| Repository / isolation | `services/api/app/db/**` | Tenant isolation (#1), deletion (#2) |
| Gateway | `services/api/app/services/gateway.py` | Temporary chat (#6), degradation (#4) |
| Write/audit | `services/api/app/services/{write_service,audit}.py` | Auditability (#7), provenance (#3) |
| Migrations | `infra/db/**` | Schema + RLS posture |
| Evals/tests | `evals/**`, `services/api/tests/**` | The invariant guard itself |
| Docs/claims | `README.md`, `docs/**` | Overclaimed guarantees |

## Required evidence

- Repository/isolation changes require tenant-isolation and deletion tests to pass.
- Policy broker / redaction changes require the adversarial block/pending evals.
- Gateway changes require the temporary-chat and retrieval tests.
- Any change runs the full `pytest` suite and `evals/run_evals.py`.

## Non-goals

The gate must not: run inside the memory runtime, decide policy, modify guardrails
automatically, access real tenant data, or approve/merge PRs. It cannot override
deterministic test/eval failures.

## Workflow security notes

- Uses the `pull_request` event (not `pull_request_target`), so PR code does not
  run with elevated repository secrets.
- No LLM keys are configured; review runs stay offline and deterministic.
- PR comments are advisory and may be skipped on forked PRs where GitHub limits
  token write permissions; deterministic results still stand.
