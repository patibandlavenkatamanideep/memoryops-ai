# Railway smoke tests

There are **two** smoke tests, and they answer different questions. Using the wrong
one as release evidence is the mistake this page exists to prevent.

| Script | Question it answers | Release gate? |
|--------|---------------------|---------------|
| [`scripts/railway_smoke_test.py`](../../scripts/railway_smoke_test.py) | Is the stack up and serving? | **No** |
| [`scripts/release_smoke_v24.py`](../../scripts/release_smoke_v24.py) | Does the deployed authorization boundary match the release claim? | **Yes** |

## Release gate — `release_smoke_v24.py`

The production release gate since v2.4. It drives seven principals, the four JWT
role-claim states, cross-tenant isolation, a full write→delete→evidence lifecycle,
and the web/BFF boundary against a live deployment. See
[`docs/releases/RELEASE-PROCESS.md`](../releases/RELEASE-PROCESS.md).

```bash
python scripts/release_smoke_v24.py \
  --api-url https://<api>.up.railway.app \
  --web-url https://<web>.up.railway.app \
  --jwt-key "$MEMORYOPS_AUTH_JWT_KEY" \
  --production
```

Gate: `FAILED 0`, `SKIPPED 0`, `RESULT: PASS`. Exit codes are `0` pass, `1` fail,
`2` incomplete (something was skipped), `3` environment fault (e.g. no local CA
bundle — see below).

## Quick deployment / liveness smoke — `railway_smoke_test.py`

**This is not the release gate.** It predates authenticated route enforcement: it
makes unauthenticated `POST /api/chat` calls and cannot exercise the authorization
boundary at all. Treat a green run as *"the stack is up"* and nothing more.

In particular, **do not cite it as evidence of authorization correctness.** Against
a production-profile deployment (`MEMORYOPS_AUTH_MODE=jwt`) its write/read checks
will fail on 401 — which is the API behaving correctly, not a defect.

It is kept because a dependency-free liveness check that runs from any shell is
genuinely useful during a deploy, before there is any reason to reach for the gate.

Run it after the four services are up (see [railway.md](railway.md)).

## Automated

[`scripts/railway_smoke_test.py`](../../scripts/railway_smoke_test.py) is
stdlib-only (no install needed) and exits non-zero on any required failure:

```bash
python scripts/railway_smoke_test.py \
  --api-url https://memoryops-api.up.railway.app \
  --web-url https://memoryops-web.up.railway.app
```

Flags:
- `--web-url` is optional; omit to skip the web check.
- `--skip-evals` skips the optional eval check.

## What it checks

| # | Check | Request | Pass condition |
|---|-------|---------|----------------|
| 1 | API liveness | `GET /healthz` | `200`, `{"status":"ok"}` |
| 2 | API readiness | `GET /readyz` | `200`, `ready: true` |
| 3 | Web loads | `GET <web>/` | `200` (skipped without `--web-url`) |
| 4 | Memory **write** | `POST /api/chat` "Remember …" | `200` + `loop_evidence` present |
| 5 | Memory **read** | `POST /api/chat` recall query | `200`; recall reported (not enforced — graceful degradation) |
| 6 | Loop endpoint | `GET /api/loops` + `/api/loops/runs` | `200`, non-empty definitions |
| 7 | Eval endpoint | `POST /api/evals/run` | optional; warns on non-200 |

The write/read pair uses a throwaway tenant/user (`tenant_smoke` / `user_smoke`)
and a random token so it never collides with real data. Read recall is reported
but **not** required to pass, because retrieval degrades gracefully (invariant #4)
and recall depends on the embedding provider configured for the environment.

## Manual spot checks

```bash
API=https://memoryops-api.up.railway.app

curl -fsS $API/healthz                       # {"status":"ok","version":"…"}
curl -fsS $API/readyz                         # {"ready":true,"storage":"postgres",…}

# write
curl -fsS -X POST $API/api/chat -H 'content-type: application/json' \
  -d '{"tenant_id":"tenant_smoke","user_id":"user_smoke","message":"Remember my smoke token is abc123."}'

# read
curl -fsS -X POST $API/api/chat -H 'content-type: application/json' \
  -d '{"tenant_id":"tenant_smoke","user_id":"user_smoke","message":"What is my smoke token?"}'

curl -fsS $API/api/loops | head -c 400         # loop definitions
curl -fsS $API/api/loops/runs | head -c 400    # recent loop runs
curl -fsS -X POST $API/api/evals/run -H 'content-type: application/json' -d '{}'
```

Then load the web URL in a browser and confirm the landing, chat, and `/loops`
pages render and the chat shows loop-evidence chips.

## Exit criteria

A deploy is healthy when checks 1–6 pass. Check 7 (evals) is informational —
investigate a non-200 but it does not block the release.
