# Release process — evidence, SHAs, and tagging

How a MemoryOps AI release records what it proved, and why the evidence is split
across two artifacts instead of one file.

Written after v2.4, which had to re-cut its release candidate twice: once because the
candidate turned out not to be deployable, and once because recording the deployment
evidence changed the SHA the evidence described.

---

## 1. The two artifacts

Release evidence lives in two places, on purpose.

### In-tree manifest — `docs/releases/vX.Y-release-truth.md`

Committed, tagged, and permanent. Contains everything knowable **before** the tag:

- the release candidate SHA and how it was chosen
- code evidence: test totals, lint, evals, benchmark, guards, secret scans — each with
  the command that produces it
- deployment evidence from the **validated** candidate deployment
- what the release explicitly does **not** claim

### GitHub Release body

Written after the tag exists. Contains everything only knowable **after** it:

- the smoke result executed against the exact tagged, deployed commit
- final confirmation that each service reports the tagged SHA
- links to the manifest at its immutable blob URL

---

## 2. Why they cannot be one artifact

A release manifest cannot contain:

- the SHA of the commit that introduces it, nor
- the result of a run that postdates it.

Both are self-reference. Editing the manifest to record a smoke result changes the
commit the result describes, so the new commit needs a new run, which needs another
edit. That regress is not a process failure to be tidied up — it is a property of
putting a document inside the thing it describes.

The escape is to stop trying. The tagged tree carries evidence that is true at tag
time; the Release body carries evidence generated afterwards. Neither lies, and
neither needs rewriting.

> **Do not** edit the manifest after the final verification run to "finish" it.
> That creates a new SHA and restarts the problem. This is exactly what happened in
> v2.4, and it cost a full re-verification cycle.

---

## 3. Release sequence

```
candidate SHA
  → CI green at that SHA
  → clean-worktree verification at that SHA
  → deploy that SHA
  → production smoke against that deployment
  → (if the manifest must change) one evidence commit
  → re-verify + redeploy the final SHA
  → STOP editing the tree
  → tag
  → record the tagged-deployment smoke in the GitHub Release body
```

The step most often skipped is **deploy before tag**. A candidate that passes every
code gate can still be undeployable — v2.4's first candidate was, twice over:

- a config-as-code `startCommand` containing `$PORT`, which does not expand in exec
  form, so the process received the literal string;
- a web layout that resolved its runtime mode at build time rather than per request.

Neither was expressible as a unit test. Only a deployment found them.

---

## 4. Preserving SHA identity

When a release claims

```
CI SHA = verified SHA = deployed SHA = tag SHA
```

every step between candidate and tag must preserve the commit object.

**Required once the candidate SHA is established:**

- **No squash merge** — produces a new commit, so the tag would name something CI
  never tested.
- **No rebase merge** — rewrites the commit.
- **Fast-forward only.** `git push origin <branch>:main` when the branch's parent is
  the current `main`. Confirm first:

```bash
git rev-parse HEAD^                              # must equal current origin/main
git merge-base --is-ancestor origin/main HEAD    # must succeed
```

- Check for branch protection or rulesets that would force a merge commit **before**
  committing to this approach, not after.

For ordinary work none of this applies — squash away. It matters only between
establishing a candidate and tagging it.

---

## 5. Docs-only successors

Sometimes the manifest must change after the candidate is validated — correcting a
superseded RC reference, say. That successor commit is legitimate provided it changes
**only** documentation, and provided the claim is stated precisely:

> This commit changes no runtime source or configuration input consumed by the API,
> web, or worker Dockerfiles. The API builds from `services/api`, the web from
> `apps/web`, and the worker copies only `services/api` and `services/worker` — no
> build context includes `docs/`. The runtime source is therefore equivalent to
> `<candidate>`. Normal build and deployment risk still applies; this is a statement
> about build inputs, not a guarantee of identical image digests.

Verifiable by anyone:

```bash
git diff <candidate> <successor> -- ':(exclude)docs'   # must be empty
```

Say **equivalent runtime source**, not *"byte-identical images"* or *"risk-free"*.
The build still runs, and a rebuild can still fail. Redeploy and re-verify the
successor rather than assuming it inherits the candidate's evidence.

---

## 6. Release gate

A release is gated on `scripts/release_smoke_v24.py` against the deployed stack:

```bash
python scripts/release_smoke_v24.py \
  --api-url https://<api> --web-url https://<web> \
  --jwt-key "$MEMORYOPS_AUTH_JWT_KEY" --production
```

Required: `FAILED 0`, `SKIPPED 0`, `RESULT: PASS`.

**Skipped is not passed.** The harness exits `2` (`INCOMPLETE`) when a section did
not run, because missing evidence is not evidence of absence.

Exit codes: `0` pass · `1` fail · `2` incomplete · `3` environment fault.

Read individual lines, not only the totals. Some checks **record** rather than assert
— `/metrics` reports its policy either way, so `[PASS] /metrics is protected` and
`[NOTE] /metrics is PUBLICLY reachable` both leave the run green.

`scripts/railway_smoke_test.py` is **not** a release gate — it predates authenticated
route enforcement. See [`../deployment/railway-smoke-test.md`](../deployment/railway-smoke-test.md).

---

## 7. Release body template

```markdown
## Deployment evidence — tagged commit <SHA>

| Service | Deployed commit |
|---------|-----------------|
| memoryops-api    | <SHA> |
| memoryops-web    | <SHA> |
| memoryops-worker | <SHA> |

PASSED <n>   FAILED 0   SKIPPED 0
RESULT: PASS

- `GET /readyz` → {"ready":true,"degraded":false}
- `GET /healthz/workers` → {"healthy":true}
- `GET /metrics` → 401 (operator-protected)
- `GET /docs`, `/redoc`, `/openapi.json` → 404

Full release truth: docs/releases/vX.Y-release-truth.md @ <SHA>
```

Never paste a signing key, operator password, or connection string into a Release
body — including inside pasted smoke output. Check before publishing.
