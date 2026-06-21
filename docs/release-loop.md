# Release Gate Loop

`release.gate` models release discipline as a loop. It is intentionally manual:
MemoryOps does not auto-tag or auto-create GitHub releases from the application.

## Purpose

Ensure every version is tagged only after validation evidence exists.

## Trigger

A maintainer prepares a `v0.x` release.

## States

```text
observed -> executed -> verified -> audited -> completed
```

Failure path:

```text
observed/executed/verified -> failed -> audited
```

## Policy Gates

- Tests pass.
- Evals pass.
- Lint/build pass, or environment limitation is documented.
- Release notes are prepared.
- Known limitations are documented.
- Tag points to the correct commit.
- No AI co-author trailer is added to commits.

## Evidence

- Commit hash.
- Test result.
- Eval result.
- PR invariant gate result.
- Build/lint result or caveat.
- Release title.
- Manual release notes.

## v0.2.2 Recommended Tag

```bash
git tag -a v0.2.2 <commit_hash> -m "MemoryOps AI v0.2.2 - Loop Engineering Architecture Layer"
git push origin v0.2.2
```

GitHub release title:

```text
MemoryOps AI v0.2.2 - Loop Engineering Architecture Layer
```
