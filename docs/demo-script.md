# Demo script — MemoryOps AI

A judge should understand the system in ~3 minutes. Run the API (`uvicorn app.main:app`) and the web
app (`npm run dev`), or use `curl` against `http://localhost:8000`.

Default seed identities: `tenant_id=tenant_demo`, `user_id=user_demo` (and a second tenant
`tenant_acme`/`user_acme` for the isolation demo).

## Demo 1 — Save memory
```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' -d '{
  "tenant_id":"tenant_demo","user_id":"user_demo",
  "message":"Remember that I prefer enterprise-style AI architecture explanations with clear phases and no emojis."
}' | jq
```
**Expect:** extractor detects a `procedural` memory, policy broker → `SAVE`, audit `memory_created`,
memory appears in the dashboard.

## Demo 2 — Use memory
```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' -d '{
  "tenant_id":"tenant_demo","user_id":"user_demo",
  "message":"Explain how my memory system should be positioned."
}' | jq '.used_memories'
```
**Expect:** the preference is retrieved; response reflects enterprise style; `used_memories` shows the
memory-used badge.

## Demo 3 — Block a secret
```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' -d '{
  "tenant_id":"tenant_demo","user_id":"user_demo",
  "message":"Remember that my API key is sk-test-123456789abcdefghij."
}' | jq '.candidate_memories'
```
**Expect:** policy broker → `BLOCK`, nothing stored, audit `memory_blocked`.

## Demo 4 — Temporary chat
```bash
curl -s localhost:8000/api/chat -H 'content-type: application/json' -d '{
  "tenant_id":"tenant_demo","user_id":"user_demo","temporary_chat":true,
  "message":"Remember that I like casual answers."
}' | jq
```
**Expect:** no memory written, no memory retrieved, audit `temporary_chat_skipped`.

## Demo 5 — Forget memory
```bash
# list, grab an id, then:
curl -s -X DELETE localhost:8000/api/memories/<id> \
  -H 'content-type: application/json' \
  -d '{"tenant_id":"tenant_demo","user_id":"user_demo"}' | jq
```
**Expect:** status → `deleted`, future retrieval excludes it, audit `memory_deleted`.

## Demo 6 — Admin governance
Open the **Admin** page (or `GET /api/audit?tenant_id=tenant_demo`).
**Expect:** metrics (writes, blocks, deletes, retrievals), audit event table, invariants, and the
architecture story are all visible.

## Bonus — Tenant isolation
Save a memory under `tenant_acme/user_acme`, then query memories as `tenant_demo/user_demo` and
confirm the acme memory never appears.
