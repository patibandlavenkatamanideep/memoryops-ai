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
  together**; bump both in the same PR. CI (`publish-sdk.yml`) derives the expected
  version from the SDK `pyproject.toml` and fails the release unless the `sdk-v*` tag,
  `memoryops.__version__`, **and** `app.__version__` all match it. Publication is
  **tag-only** — a manual `workflow_dispatch` run builds and verifies but never
  uploads.

## Release checklist

1. Ensure `main` is green: `pytest -q`, `ruff check app`, `python evals/run_evals.py`,
   `npm run build`. See [docs/release-loop.md](docs/release-loop.md) for the
   `release.gate` loop contract.
2. Decide the version and a one-line summary.
3. Tag and push (use the next platform version — `v2.2` shipped most recently):
   ```bash
   git tag -a v2.3 -m "MemoryOps AI v2.3 — <summary>"
   git push origin v2.3
   ```
4. Create the GitHub Release with the body template below:
   ```bash
   gh release create v2.3 --title "MemoryOps AI v2.3 — <summary>" --notes-file notes.md
   ```

## SDK release checklist

The Python SDK publishes to PyPI from `.github/workflows/publish-sdk.yml`. The
`publish` job selects its auth at run time: it **prefers the `PYPI_API_TOKEN`
secret when configured, and otherwise falls back to PyPI Trusted Publishing
(OIDC, no long-lived secret)**. Both paths use `pypa/gh-action-pypi-publish`.

> **Hardening intent:** a project-scoped token or working OIDC is preferable to a
> broad long-lived token. Once Trusted Publishing is verified end-to-end, retire
> `PYPI_API_TOKEN` so the workflow always takes the OIDC path.

Configure PyPI once (Trusted Publishing path) with:

- project: `memoryops-sdk`
- owner/repository: `patibandlavenkatamanideep/memoryops-ai`
- workflow: `.github/workflows/publish-sdk.yml`
- environment: `pypi`

Then release the SDK (publication is **tag-only**; the manual dispatch is a
build-and-verify dry run that never uploads):

```bash
# 1. Dry run: build + twine check + clean-wheel install + version agreement, no upload.
gh workflow run publish-sdk.yml
# 2. Publish by pushing the tag (must equal the SDK pyproject / app.__version__).
git tag -a sdk-v1.0.0 -m "memoryops-sdk 1.0.0"
git push origin sdk-v1.0.0
# 3. Verify from a clean environment.
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

## Remaining roadmap

The v0.1–v2.2 milestones have all shipped (see `CHANGELOG.md` and the GitHub
Releases). The remaining, forward-looking work:

- **Atomic write + audit persistence** — commit the memory row and its audit event
  in one transaction (or via a transactional outbox with durable delivery), closing
  the crash window where a stored memory can lack its audit record.
- **Live-provider validation** — real OpenAI/Anthropic/Gemini latency, fallback
  frequency, and correctness in the hot path (beyond the offline stub replay).
- **Retrieval-quality comparison** — vector-only vs BM25-only vs hybrid
  (Recall@k / MRR / nDCG) on a labelled set.
- **Distributed rate limiting** — a shared (Redis-backed) limiter to replace the
  per-process counter, for a real multi-replica limit.
- **External baseline** — benchmark against a comparable external memory system.
- **Performance remeasurement** — re-run the corrected load harness (and the
  Postgres/pgvector sweep) to replace the confounded first-pass numbers in
  `docs/performance.md`.
