# Contributing to MemoryOps AI

## Principles

1. **Invariants are non-negotiable.** Any change must preserve the seven
   invariants in [README.md](README.md#enterprise-invariants). The eval harness
   and tests guard them.
2. **Policy before storage.** New write paths route through the policy broker.
3. **Everything is audited.** New lifecycle actions call `AuditService.record`.
4. **Degrade gracefully.** External calls (LLM, embeddings, DB reads) are wrapped
   with the reliability primitives; failures never break the response path.

## Dev setup

```bash
# API
cd services/api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
ruff check app

# Eval harness
python ../../evals/run_evals.py

# Web
cd ../../apps/web
npm install && npm run build
```

## Before opening a PR

- `pytest -q` passes in `services/api`.
- `ruff check app` is clean.
- `python evals/run_evals.py` exits 0 (all critical invariants pass, rate ≥ 80%).
- `npm run build` succeeds in `apps/web`.
- Dependencies stay **exact-pinned** (no ranges) — see ADR notes and
  [SECURITY.md](SECURITY.md).

## PR review

PRs run two workflows (see [.github/workflows](.github/workflows)):
- **CI** — tests + lint + eval harness.
- **Invariant Evidence Gate** — detects changes to security/governance-sensitive
  surfaces and posts an evidence checklist (policy:
  [docs/ai-pr-review-policy.md](docs/ai-pr-review-policy.md)).

## Releases

We tag releases `vX.Y[.Z]` with GitHub Releases. See [RELEASING.md](RELEASING.md).
