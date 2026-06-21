# Railway smoke test

Post-deploy verification for a live MemoryOps AI stack on Railway. Run it after
all five services are up (see [railway.md](railway.md)).

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
