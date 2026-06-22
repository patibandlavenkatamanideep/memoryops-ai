# Agent Handoff — MemoryOps AI

_Last updated: 2026-06-22 (end of v0.12 build; PR #11 open)._

## Current state (verified)

- **Branch:** `feat/v0.12-hosted-demo` (working tree clean except this untracked HANDOFF).
- **HEAD:** `18f2a5b feat: v0.12 interactive playground + hosted demo`.
- **Stacking:** `feat/v0.12-hosted-demo` is **stacked on `feat/v0.11-assistant-sdk`**
  (branched from the v0.11 tip, NOT from main), because v0.11 (PR #10) is not merged
  yet. This avoids rollout/README doc divergence. Until #10 merges, PR #11's diff
  includes the v0.11 commit; it reduces to just v0.12 once #10 lands.
- **Open PRs:**
  - [#10](https://github.com/patibandlavenkatamanideep/memoryops-ai/pull/10) — v0.11 SDK → main, **OPEN**.
  - [#11](https://github.com/patibandlavenkatamanideep/memoryops-ai/pull/11) — v0.12 playground → main, **OPEN** (this work).
- **main:** `0036da4` (v0.10). **Tags:** through `v0.10`; v0.11/v0.12 not tagged.

### Milestone status
- v0.9 dashboard, v0.10 retention — merged + tagged.
- v0.11 SDK — **PR #10 open** (not merged/tagged).
- v0.12 interactive playground + hosted demo — **PR #11 open** (not merged/tagged).
- v1.0 — remaining.

## v0.12 — what was built (PR #11, commit 18f2a5b)

Interactive public **Playground** that drives the **real** governed pipeline from
`services/api` **in-process**, against a fresh **in-memory** store per browser
session. Additive only — no `services/api` changes; not the production UI.

### Files (10 files)
- `apps/playground/streamlit_app.py` — 4 tabs (Capture & ask · Memories &
  governance · Retention preview · Audit trace). **Entrypoint named
  `streamlit_app.py` to avoid shadowing the backend `app` package** (see Failures).
- `apps/playground/requirements.txt` (`-r ../../services/api/requirements.txt` +
  streamlit), `Dockerfile` (build from repo ROOT — needs services/api),
  `railway.toml` (optional demo service, not a core service), `README.md`.
- `docs/playground.md` (architecture + demo-safety + demo-only vs production),
  `docs/images/playground/README.md` (screenshot/GIF capture guide).
- Modified: `README.md` (layout + "v0.12" section + roadmap + docs link),
  `docs/rollout.md` (Phase 9 + roadmap), `CLAUDE.md` (layout entry).

### Design
- Per Streamlit session: fresh `InMemoryRepository` + `Gateway` + `AuditService`
  in `st.session_state`, scope `playground/visitor_<rand>`. No DB, no secrets, no
  network (stub LLM + embeddings). Drives the real `gateway.handle_chat`,
  `db.governance` (legal hold / pin / consent), `services.retention.evaluate`,
  and `workers.runner.run_jobs` — so behavior is faithful, not reimplemented.

## Commands run (and results)
- `services/api/.venv/bin/python -m pytest -q` (in services/api) → **249 passed, 1
  skipped** (unchanged; no backend code touched).
- `services/api/.venv/bin/ruff check app ../../apps/playground` → **All checks passed**.
- Playground smoke (stub Streamlit, real in-process pipeline): seed → policy
  decisions (`SAVE`/`DROP_LOW_UTILITY`) → legal-hold blocks delete → retention
  outcome `held` → all 7 lifecycle workers `ok=True` → 26 audit events → hybrid
  retrieval used seeded memories. ✅
- `py_compile streamlit_app.py` → OK.
- PR gate `--base feat/v0.11-assistant-sdk --head HEAD` and `--base main --head HEAD`
  → **PASS, 0 rules armed** (additive).
- `git push -u origin feat/v0.12-hosted-demo`; `gh pr create` → PR #11.

## Failures encountered (and fixes)
1. **Name collision:** the entrypoint `app.py` shadowed the `services/api` **`app`
   package**, so `from app.db import ...` resolved to the playground module →
   `ModuleNotFoundError: No module named 'app.db'`. **Fix:** rename entrypoint to
   `streamlit_app.py` (also Streamlit Cloud's default). Smoke then passed.
2. **ruff** flagged an unused `Status` import → removed via `ruff --fix`.
3. Earlier this session: a `mv`/`git mv` Bash call was blocked by a transient
   classifier outage; re-ran the rename successfully after.

No outstanding failures. Everything green.

## Key decisions
- **Stack v0.12 on v0.11** (not branch from main) to keep rollout/README docs
  consistent and avoid merge churn; PR #11 targets main and self-reduces post-#10.
- **Drive the real pipeline in-process** (not via the SDK/HTTP) for true
  per-session isolation and to showcase actual governance behavior live.
- **Hostable without infra** — Streamlit Community Cloud (`streamlit_app.py`) or an
  optional Railway demo service; no Vercel, not one of the five core services.
- Screenshots/GIF + hosted link deferred to operator (need a live browser/host);
  shipped a capture guide instead of binary placeholders.
- **Did not** tag/merge/release.

## Next 3 actions
1. **Land the stack in order:** merge **PR #10 (v0.11)** to main + tag `v0.11`;
   then PR #11's base auto-updates and its diff reduces to just v0.12 — merge
   **PR #11**, tag `v0.12`. Run `git fetch --tags` locally afterward.
2. **Finish v0.12 operator steps:** host the playground (Streamlit Community Cloud
   or Railway), capture the 4 tab screenshots + demo GIF per
   `docs/images/playground/README.md`, and wire the demo link + images into the
   README hero.
3. **Start v1.0 — Production-Ready Governed Memory Runtime:** stabilize API + SDK
   contracts, complete deployment guide + security model docs, README polish,
   known-limitations page, and fold in the hosted demo link. Branch from updated
   `main` once #10/#11 land.

## Pointers
- Playground: `apps/playground/README.md`, `docs/playground.md`, `docs/images/playground/`.
- Results dashboard (v0.9 evidence): `apps/results-dashboard/`, `docs/results-dashboard.md`.
- SDK (v0.11): `packages/memoryops-sdk/README.md`, `docs/assistant-sdk.md`, `infra/adr/ADR-014-assistant-sdk.md`.
- Roadmap/phases: `docs/rollout.md`. PR-gate: `scripts/pr_invariant_gate.py`. Invariants: `CLAUDE.md`.
- Tooling: no `python`/`pytest` on PATH — use `services/api/.venv/bin/python` (Python 3.14).
