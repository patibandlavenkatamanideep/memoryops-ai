# MemoryOps AI — Playground (v0.12)

An **interactive public demo** of MemoryOps AI. Unlike the read-only v0.9 results
dashboard, the playground lets you *drive* the governed memory lifecycle and watch
governance change the assistant's behavior live — with a full audit trail.

> **Demo-only, safe to host.** The playground runs the **real** governed pipeline
> from [`services/api`](../../services/api) **in process**, against a **fresh
> in-memory store created per browser session**. There is no database, no auth, no
> secrets, and no network (stub LLM + stub embeddings). Nothing is persisted and
> there is no real user data. The Next.js app (`apps/web`) remains the official
> product UI.

## What you can do

1. **Capture & ask** — type a memory, then ask a question that should use it. See
   the policy broker's per-message decisions (`SAVE` / `DROP_LOW_UTILITY` /
   `BLOCK`) and which memories were retrieved to answer.
2. **Memories & governance** — apply a **legal hold** (deletion is then refused,
   fail-closed, like the API's HTTP 409), **pin**, **withdraw consent**, or
   **delete**. Run the **lifecycle workers** (decay · archive · retention ·
   deletion verification · compaction) over your session.
3. **Retention preview** — read-only preview of what the retention worker *would*
   do under a policy pack. Deletes nothing.
4. **Audit trace** — every governed action appends a content-free audit event.

## Run it

### Locally
```bash
cd apps/playground
pip install -r requirements.txt      # pulls services/api deps + streamlit
streamlit run streamlit_app.py       # http://localhost:8501
```
No environment variables required (`MEMORYOPS_STORAGE` defaults to `memory`).

### Streamlit Community Cloud (simplest hosting)
Point it at this repo with **main file path** `apps/playground/streamlit_app.py`.
It installs `apps/playground/requirements.txt` and the app adds `services/api` to
`sys.path` automatically. No secrets to configure.

### Docker / Railway (optional)
Build from the **repository root** (the image needs `services/api`):
```bash
docker build -f apps/playground/Dockerfile -t memoryops-playground .
docker run -p 8501:8501 -e PORT=8501 memoryops-playground
```
On Railway, deploy it as an *optional* demo service (not one of the five core
services). Because the Dockerfile copies `services/api`, the build context **must
be the repo root**, so configure the service as:

- **Root Directory:** `/` (repo root)
- **Config File (config-as-code):** `railway/playground.railway.json`

That config sets `builder = DOCKERFILE`, `dockerfilePath = apps/playground/Dockerfile`,
and the Streamlit start command on `$PORT`. **Do not** set the Root Directory to
`apps/playground` — the `COPY services/api` step would fail and Railway would fall
back to its Railpack auto-detector. See [docs/playground.md](../../docs/playground.md).

## How it stays safe

- **In-memory only** — each session builds its own `InMemoryRepository`; resetting
  or reconnecting starts clean. No Postgres, no shared state across sessions.
- **No secrets / no network** — LLM and embedding providers default to
  deterministic offline stubs; no API keys are read.
- **Server-authoritative** — the playground does not reimplement governance; it
  calls the same gateway / policy broker / governance / retention code the product
  uses. What you see is how MemoryOps actually behaves.

## Files
```text
apps/playground/
  streamlit_app.py     # entrypoint (named to avoid colliding with the `app` package)
  requirements.txt     # -r services/api/requirements.txt + streamlit
  Dockerfile           # optional; build from repo ROOT (copies services/api)
  README.md
railway/
  playground.railway.json   # Railway config: DOCKERFILE builder + start command
```
The Railway service config lives at repo level (`railway/playground.railway.json`),
not in this folder, because the Docker build context must be the repository root.
