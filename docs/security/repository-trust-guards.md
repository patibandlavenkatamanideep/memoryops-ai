# Repository trust guards

Structural checks for regressions this repository has actually had. Each one exists
because the corresponding mistake was made here, reached `main`, and was found by
reading rather than by a check.

Run them:

```bash
python scripts/repo_trust_guards.py            # all guards
python scripts/repo_trust_guards.py --guard sys-path-mutation
```

They also run as `services/api/tests/test_repo_trust_guards.py`, where every guard has
a **negative test** proving a representative bad edit makes it fail. A guard nobody has
watched fail is a guard nobody knows works — the positive half ("the repo is clean")
passes just as well when the guard itself is broken.

## Why AST and tokens, not grep

Every guard here was first attempted as a string search, and every one fired on prose
*about* the problem:

| Search | False positive |
| --- | --- |
| `sys.path.insert` | the worker's `pyproject.toml` and `Dockerfile`, both explaining that the call was removed |
| `DEMO_TENANT` | `lib/api.ts`, documenting the constants it no longer exports |
| `import redis` | `test_no_unused_infrastructure.py`'s own docstring |

A guard that fires on its own documentation trains people to ignore it. So these
parse: `ast` for Python structure, `tokenize`/AST for string literals, and
string-aware comment stripping for TypeScript. Only what the parser says is *code* is
reported.

This is not theoretical. An early draft of the test asserting the worker no longer
mutates `sys.path` did so with `assert "sys.path" not in source` — and failed on the
comment recording why the mutation had been removed. The same false positive,
reproduced inside the guard's own test suite.

## What each guard proves

### `sys-path-mutation`

**Claim:** no shipped service code rewrites its own import path.

`services/worker/jobs.py` inserted `../api` into `sys.path` at import time so it could
reach the API package without depending on it — while `services/worker/pyproject.toml`
stated that no such call remained in a production entrypoint. The file ships in the
worker image, so the claim was false wherever it was read.

A service that rewrites its import path at startup can resolve a *different* dependency
set than the service it imports from, and the failure surfaces as version skew nobody
can trace back. The worker declares the API as an ordinary dependency, so the mutation
was also unnecessary.

Detects `sys.path.append/insert/extend/remove/pop/clear`, `sys.path = …`,
`sys.path += …` and `sys.path[i] = …`, however `sys` was imported. Scoped to
`services/api/app`, `services/worker` and the SDK package. Tests and `scripts/` are
excluded: they are not shipped, and reaching a sibling package there is legitimate —
`test_repo_trust_guards.py` does it to import the guards.

### `committed-secret-literal`

**Claim:** no credential-shaped value is written literally into tracked source.

Tests for secret *detection* need input that looks like a real credential. Writing it
inline commits a secret-shaped string, which is what scanners exist to catch — and they
cannot tell a fixture from a live key. Gitleaks flagged this here twice. Because it
scans commit *ranges*, deleting the literal in a later commit does not clear the branch;
it has to be squashed.

`services/api/tests/_secret_fixtures.py` is the pattern that holds: concatenate the
parts at import time, producing byte-identical input to the code under test with no
literal in the tree. This guard found one remaining violation on its first run
(`paper/harness`), now fixed the same way.

Reports two shapes, deliberately separated:

1. **A recognised credential token anywhere in a string** (`sk-…`, `ghp_…`, `AKIA…`),
   whether or not it is the whole value. Fixtures usually arrive *inside a sentence* —
   `"Remember that my API key is sk-… please"` is how a user would actually paste one
   into a chat, and secret-detection tests are exactly where such sentences live. Six
   were in this repository when the token search was added; a whole-value match found
   none of them, because none was a bare token, none was assigned to a
   credential-named variable, and every one contained whitespace.
2. **An assignment whose name means credential** (`api_key`, `client_secret`,
   `signing_key`, …) holding a dense literal — for values with no recognised shape.

The whitespace exemption applies only to (2). A credential is a dense token;
`secret = "the acquisition closes on the fourteenth"` is a sentence — it appears in
deletion tests where the variable is named for what the memory means to the *user*.
Flagging it would make the guard fire on correct code.

**Docstrings are excluded structurally**, by asking the parser which constants are
docstrings, not by inspecting the text. A docstring describing an example credential
is prose; an ordinary runtime string containing one is code. `_secret_fixtures.py`
explains the `sk-` shape in its own docstring, and so does the guard module — deciding
that by pattern would be the grep-shaped mistake this whole file argues against.

Token matching is boundary-anchored, so `"prefix-sk-live…-suffix"` is not a finding,
and runtime concatenation leaves no constant containing the token — the prescribed fix
does not trip the guard.

### `demo-identity-in-server-code`

**Claim:** server-executed web code never names the demo tenant or user.

The BFF exists so identity is attached on the server and cannot be chosen by the
client. A hard-coded demo scope in that path defeats the point. Two instances shipped:
`lib/api.ts` exported `DEMO_TENANT`/`DEMO_USER` constants that pinned every request to
one shared persona, and a demo session could mint a `tenant_admin` credential.

`lib/identity.ts` is the single exception by construction — it *implements* demo mode
and refuses it in production. Everything else on the server resolves identity through
it.

Comment stripping is string-aware: a `//` inside a quoted string is not a comment, and
a demo literal inside a string still counts. The value is the bug.

### `retired-infrastructure`

**Claim:** a removed dependency has not crept back as configuration.

Redis was declared in `Settings`, started by Compose, health-gating both services'
startup, and listed as a required Railway service — while no runtime code imported a
client. A declared-but-unused dependency is a service to pay for, a health check that
can fail a deploy, and an architecture diagram that misleads every reader.

**This is not a ban.** If something genuinely starts using Redis, a real import will
exist, this guard will fail, and the correct response is to update it to assert the
consumer — not to allowlist the config.

Import matching resolves the module name, so `import redis_notes` and `from redisx
import …` are not confused for `redis`.

### `railway-deployment-config`

**Claim:** the Railway configuration in the repository describes the deployment that
actually runs.

v2.4 shipped a release candidate that passed every code gate and could not be
deployed. Two defects caused it, and neither was expressible as a unit test:

- `railway/api.railway.json` declared `startCommand` with `--port $PORT`. A
  config-as-code start command on a Dockerfile service runs in **exec form without
  shell expansion**, so uvicorn received the four characters `$PORT`. This repository
  had *already documented* that exact failure for the playground service; the API hit
  it independently anyway, which is why it is now a guard rather than a paragraph.
- `railway/web.railway.json` health-checked `/`, which answers `307 → /signin` in
  authenticated mode. It works in demo mode, which is precisely why the mistake
  survives review.

Both were fixed in the Railway dashboard. That restored production and left the
repository describing a deployment that no longer existed — so anything built from the
checked-in config reproduced the outage.

The guard asserts that every canonical `railway/*.railway.json` exists, that no
`startCommand` anywhere contains a literal `$PORT`, that `api`/`web`/`worker` declare
no `startCommand` at all (their Dockerfile `CMD` is authoritative), that the web
health check is not `/`, and that no service has two competing config sources.

**Parsed, not grepped** — for the usual reason. `docs/deployment/railway.md` explains
the `$PORT` failure at length, and a substring search would fail the check that exists
to prevent it.

**No exceptions.** Every service must have exactly one config source. The API briefly
carried a transitional `services/api/railway.toml` alongside its canonical JSON while
Railway still read the TOML; that allowance was named rather than shape-based
specifically so that finishing the migration removed it by deletion. It is gone, and
a duplicate for any service — the API included — is now a finding.

The playground is deliberately outside `DOCKERFILE_OWNS_START`: its Dockerfile `CMD`
is `sh -c "streamlit run … --server.port ${PORT:-8501} …"`, which *does* expand
`$PORT` because it runs through a shell. It is the reference implementation for
dynamic port binding, not an exception to the rule.

## Adding a guard

Add the function to `scripts/repo_trust_guards.py`, register it in `GUARDS`, and add
both halves of the test. The registration is checked: a guard that exists but is not in
`GUARDS` never runs.

Keep the scope narrow. These are structural regressions with a history in this
repository, not general linting — style, dependency hygiene and framework migrations
belong elsewhere.
