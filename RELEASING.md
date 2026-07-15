# Releasing MemoryOps AI

MemoryOps AI ships in versioned GitHub Releases, following the same convention as
[RelayOps](https://github.com/patibandlavenkatamanideep/relayops).

## Versioning

There are **two independent tracks** (see
[docs/api-stability.md](docs/api-stability.md#two-version-tracks)):

- **Platform release** — git tags `vMAJOR.MINOR[.PATCH]` (e.g. `v2.2`), the README
  badge, and `CHANGELOG.md`. `MINOR` for new capabilities, `PATCH` for
  fixes/hardening. The tag + GitHub Release are the source of truth for "what shipped".
- **API + SDK contract** — `app.__version__` and `packages/memoryops-sdk`
  `pyproject.toml`, released under `sdk-vX.Y.Z` tags. These two **must always move
  together**; bump both in the same PR. CI (`publish-sdk.yml`) fails a release whose
  `sdk-v*` tag does not match the SDK `pyproject.toml` version.

## Release checklist

1. Ensure `main` is green: `pytest -q`, `ruff check app`, `python evals/run_evals.py`,
   `npm run build`. See [docs/release-loop.md](docs/release-loop.md) for the
   `release.gate` loop contract.
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

## SDK release checklist

The Python SDK publishes through PyPI Trusted Publishing, not a long-lived API
token. Configure PyPI once with:

- project: `memoryops-sdk`
- owner/repository: `patibandlavenkatamanideep/memoryops-ai`
- workflow: `.github/workflows/publish-sdk.yml`
- environment: `pypi`

Then release the SDK:

```bash
gh workflow run publish-sdk.yml -f publish=false
git tag -a sdk-v1.0.0 -m "memoryops-sdk 1.0.0"
git push origin sdk-v1.0.0
python3 -m venv /tmp/memoryops-pypi-check
source /tmp/memoryops-pypi-check/bin/activate
pip install memoryops-sdk==1.0.0
python3 -c "import memoryops; print(memoryops.__version__)"
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
