# Releasing MemoryOps AI

MemoryOps AI ships in versioned GitHub Releases, following the same convention as
[RelayOps](https://github.com/patibandlavenkatamanideep/relayops).

## Versioning

- Git tags are `vMAJOR.MINOR[.PATCH]` (e.g. `v0.1`, `v0.2`, `v1.0.1`).
- `MINOR` for new capabilities, `PATCH` for fixes/hardening.
- The internal package version in `services/api/pyproject.toml` may lag behind the
  release tag; the tag + GitHub Release are the source of truth for "what shipped".

## Release checklist

1. Ensure `main` is green: `pytest -q`, `ruff check app`, `python evals/run_evals.py`,
   `npm run build`.
2. Decide the version and a one-line summary.
3. Tag and push:
   ```bash
   git tag -a v0.1 -m "MemoryOps AI v0.1 — <summary>"
   git push origin v0.1
   ```
4. Create the GitHub Release with the body template below:
   ```bash
   gh release create v0.1 --title "MemoryOps AI v0.1 — <summary>" --notes-file notes.md
   ```

## Release notes template

```md
## Summary
<one or two sentences on what this release delivers>

## What changed
* <bullet>
* <bullet>

## Why
<the problem this addresses>

## Validation
* `pytest -q` (services/api)
* `python evals/run_evals.py`
* `npm run build` (apps/web)
```

## Planned milestones

- **v0.1** — Phase 0 + Phase 1: design spine, write path, policy broker, audit,
  dashboard, eval harness, invariant tests.
- **v0.2** — Phase 2/3: retrieval wired into chat, governance UI actions complete.
- **v0.3** — Phase 4: pgvector embeddings, enforced RLS, expanded evals.
- **v0.4** — Phase 5: decay/reflection/conflict workers on a real scheduler.
