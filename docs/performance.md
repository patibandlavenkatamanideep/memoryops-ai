# Performance (P4.3)

> **Status: first pass — in-memory + stub providers, single process.**
> This is a starting observation, not a tuned result and not a root-cause analysis.
> Postgres/pgvector, real providers, and per-stage CPU/pool instrumentation are the
> follow-ups that would let us attribute *cause* (see the end).

> **⚠️ Read the numbers below as observations, not proofs.** The tables in this
> document were produced by an **earlier version of the harness** that created a
> fresh, unclosed `httpx.Client` per request and reused a single tenant/user across
> the whole sweep — so client/connection setup cost and a monotonically growing store
> were confounded with concurrency. The harness has since been corrected (reused
> bounded clients, a **fresh scope per scenario**, a **fixed identical seed count**,
> **≥3 repetitions**, **randomized scenario order**, and **actual before/after memory
> counts** — see [`run_perf.py`](../benchmark/perf/run_perf.py)). Re-running the sweep
> with the corrected harness is a tracked follow-up; until then, treat the specific
> figures here as indicative only.

## TL;DR

- **In the tested single-process configuration, throughput is flat and latency grows
  with concurrency** — added concurrent clients queue rather than run in parallel.
  Error rate is 0% throughout; nothing falls over, it simply does not speed up.
- **What this does *not* establish.** These runs do **not isolate** the cause. Flat
  throughput here is consistent with several non-exclusive explanations —
  per-request client/connection overhead (the old harness rebuilt a client every
  call), Starlette thread-pool limits, CPU/GIL-bound Python work in the sync
  handlers, and repository growth over the shared store — and this data cannot
  separate them. Earlier drafts asserted the effect was **CPU/GIL-bound** and that
  the fix was **horizontal scaling**; that was over-stated for what a stub +
  in-memory + confounded-harness run can show, and has been removed.
- **Implication for the async decision (P2.1): still undecided, not "rejected."**
  The I/O-bound scenario that `asyncio` actually addresses (real LLM/embedding
  network calls, Postgres round-trips) has not been measured, and the confounds
  above have not been controlled. The decision stays open pending the corrected-
  harness re-run and the Postgres/real-provider follow-ups.
- The **per-process rate limiter** works exactly as specified (30/min chat →
  fail-fast 429) and is, as the review noted, **per-replica** — not a distributed
  limit.
- Two real bugs were surfaced by this work and fixed first:
  [test-rls password masking](../services/api/tests/test_rls.py) (PR #41 follow-up)
  and the [multi-memory write 500](../services/api/app/services/gateway.py) (PR #42).

## How to reproduce

The harness ([`benchmark/perf/run_perf.py`](../benchmark/perf/run_perf.py)) drives
concurrent HTTP load against a **running** server and records throughput, latency
percentiles, and error rate. It is offline and deterministic in shape — no API
keys, no DB.

```bash
# 1. start a server with the config you want to measure
cd services/api
MEMORYOPS_STORAGE=memory MEMORYOPS_EMBEDDING_PROVIDER=stub MEMORYOPS_LLM_PROVIDER=stub \
  MEMORYOPS_RATE_LIMIT_ENABLED=false \
  uvicorn app.main:app --host 127.0.0.1 --port 8099 --log-level warning

# 2. drive load (corrected harness: reused clients, fresh scope + fixed seed per
#    scenario, repetitions, randomized order, real memory counts)
python benchmark/perf/run_perf.py --base-url http://127.0.0.1:8099 \
  --requests 400 --concurrency 1,5,10,25,50 --operations write,retrieval,chat \
  --repetitions 3 --seed-per-scenario 50 --out results.json
```

Operations map to the three user-facing paths:

| op | what it exercises |
|----|-------------------|
| `write` | a chat message that is a **statement** → extraction + policy broker + store + audit |
| `retrieval` | a chat message that is a **question** → retrieve + rank + admission + compose |
| `chat` | a representative mixed message (question, may also write) |

Raw JSON for every run below lives in
[`benchmark/perf/results/`](../benchmark/perf/results/).

## Environment & honesty caveats

- Measured on a laptop (macOS, Apple Silicon), **single uvicorn worker**, Python
  3.11, in-memory store, stub providers.
- **Absolute latencies are inflated** by this environment: macOS per-file security
  scanning made cold Python import take **70–85 s** and the first execution of each
  code path unusually slow. **Cold-start numbers here are not representative of a
  Linux/CI/Railway host** and should be ignored as absolute figures. The
  **relative** signal — how throughput and latency move with concurrency and store
  size — is what this document draws conclusions from, and that signal is robust.
- `write` and `retrieval` accumulate memories in the in-memory store as they run,
  so later scenarios see a larger store (this is realistic, and separated out in
  the dataset-size section).

## Results

### 1. Concurrency sweep — in-memory / stub / rate-limit off / hybrid ranker

400 requests per scenario. `rps` = requests/sec (higher better); latency in ms.

| op | conc | rps | p50 | p95 | p99 | errors |
|----|-----:|----:|----:|----:|----:|:------:|
| write | 1 | **62.3** | 13.6 | 23.4 | 24.9 | 0% |
| write | 5 | 38.8 | 125.0 | 133.2 | 145.4 | 0% |
| write | 10 | 35.5 | 279.9 | 346.8 | 374.7 | 0% |
| write | 25 | 32.2 | 820.0 | 973.8 | 1005.6 | 0% |
| write | 50 | 28.6 | 1717.2 | 2104.1 | 2169.7 | 0% |
| retrieval | 1 | **24.2** | 38.0 | 42.6 | 46.7 | 0% |
| retrieval | 5 | 24.5 | 200.2 | 246.1 | 300.1 | 0% |
| retrieval | 10 | 22.8 | 448.3 | 534.0 | 576.9 | 0% |
| retrieval | 25 | 20.2 | 1301.3 | 1553.1 | 1605.9 | 0% |
| retrieval | 50 | 17.5 | 2740.5 | 3413.7 | 3858.5 | 0% |
| chat | 1 | **15.1** | 62.2 | 72.8 | 87.7 | 0% |
| chat | 5 | 14.7 | 337.6 | 416.9 | 486.1 | 0% |
| chat | 10 | 13.5 | 760.2 | 942.2 | 1005.7 | 0% |
| chat | 25 | 12.5 | 2001.9 | 2327.3 | 2653.7 | 0% |
| chat | 50 | 11.6 | 4175.5 | 4985.6 | 5276.9 | 0% |

**Reading it.** Going from 1 → 50 concurrent clients:

- throughput **does not rise** (chat 15.1 → 11.6 rps; retrieval 24.2 → 17.5;
  write 62.3 → 28.6 — all flat or *down*), and
- p50 latency rises **~linearly** with concurrency (chat 62 ms → 4175 ms ≈ 67× for
  50× the clients).

Added concurrency queues rather than parallelizing, and error rate is **0%**
everywhere — nothing falls over, it simply does not get faster. **Why** it queues is
not settled by this run: the old harness rebuilt an HTTP client per request (setup
cost charged to every latency sample) and let the store grow across the sweep, so
client overhead, thread-pool limits, CPU work, and store growth are all still on the
table. See the caveat at the top.

### 2. Latency vs store size — retrieval, in-memory (linear scan)

Retrieval p50 as the store grows (single client):

| store size (approx) | retrieval p50 | p95 |
|--------------------:|--------------:|----:|
| 100   | 75.8 ms  | 99.3 ms  |
| 1,000 | 193.2 ms | 321.9 ms |

10× the store → ~2.5× the retrieval latency. Seeding beyond ~1 k memories through
the HTTP write path is **O(n²)** (every seed write also runs a read over the
growing store), so the 5 k / 10 k points were not driven locally — but the trend
above already shows the shape. The in-memory repository scans **O(n)** candidates
per query, so retrieval cost grows with the store. This is a property of the **dev/default** backend, not of
MemoryOps as designed: on Postgres, retrieval goes through the **pgvector ANN
index** (and the `VectorIndex` abstraction, ADR-021), which is sub-linear.
Postgres + pgvector **is** available and is exercised locally and in CI (the
`api-postgres` job); quantifying the ANN-vs-linear retrieval curve on it is the
tracked follow-up below. Store **memory** also grows with row count — RSS rose from
**37 MB → 234 MB** over the concurrency sweep — but the harness did not record the
exact memory count for those runs, so **no reliable per-memory byte figure can be
derived** from them. (An earlier draft's "~33 KB/memory" divided RSS by an *assumed*
row count and has been removed.) The corrected harness now records actual before/
after memory counts, so a defensible per-memory figure can be measured on the re-run.

### 3. Rate limiter — per-process, fail-fast

`MEMORYOPS_RATE_LIMIT_ENABLED=true`, defaults (chat = 30/min per tenant/IP). A
burst of 100 chat requests (concurrency 10) from one tenant/IP:

| outcome | count |
|---------|------:|
| `200` served | **30** |
| `429` rate-limited | **70** |

Exactly the 30/min cap; rejected requests fail fast (~5 ms). This confirms the
limiter works — **and** confirms the review's caveat: the counter is **in-process**.
Each replica has its own 30/min budget, and a restart resets it. It is **local
process protection, not distributed rate enforcement.** A Redis-backed limiter is
the fix for a real multi-replica limit (follow-up).

## The async decision (P2.1) — verdict: **undecided (insufficient evidence)**

The review's rule: proceed with the async rewrite only when measurements show
thread-pool / connection-pool saturation, severe p95 degradation under moderate
concurrency, provider calls serializing requests, or throughput materially below a
realistic target.

What the data actually shows:

1. **Observed:** p95 degradation and flat throughput under concurrency, at 0% errors.
2. **Not isolated:** this configuration cannot tell us *why*. A plausible contributor
   is CPU/GIL-bound Python work in the sync handlers (stub embeddings, in-memory
   cosine scan, ranking, policy) — which `asyncio` would **not** speed up — but
   per-request client/connection overhead (old harness), the fixed Starlette
   thread-pool, and store growth are equally unexcluded. The earlier version of this
   doc named CPU/GIL as *the* cause; that conclusion is not supported and has been
   withdrawn.
3. The scenario async *does* address — a route thread parked on a **network** LLM /
   embedding call or a **Postgres** round-trip while other requests wait — is
   **exactly what the stub + in-memory config removes from the measurement.** It has
   not been measured.

**Conclusion.** The decision **stays open.** This run neither justifies the async
rewrite nor rules it out; horizontal scaling (multiple uvicorn workers/replicas
behind the Railway load balancer) is a reasonable operational lever regardless, but
is **not** established here as *the* fix. Reopen P2.1 with evidence once the gating
numbers exist:

- the **corrected-harness** re-run (isolating client overhead and store growth),
- retrieval / write / chat latency + throughput with a **real** embedding + LLM
  provider (network I/O in the hot path), and
- the same against **Postgres** (connection-pool behaviour under concurrency).

If *those* show threadpool or pool saturation, stage the rewrite as the review
prescribed (async provider clients + gateway → async Postgres repo + pooling →
async routes/workers, each with before/after numbers).

## Follow-ups (measured next, tracked separately)

- [ ] **Corrected-harness re-run** of the full sweep (reused clients, fresh scope +
      fixed seed per scenario, repetitions, randomized order) to replace the
      confounded tables above with numbers that isolate concurrency.
- [ ] **Postgres + pgvector** run of the same sweep. pgvector is available and
      CI-exercised (`api-postgres`); this run quantifies In-memory-vs-Postgres and
      ANN-vs-linear retrieval.
- [ ] **Real providers** (OpenAI / Anthropic) latency + fallback frequency in the
      hot path — the I/O-bound numbers that gate the async decision.
- [ ] **Retrieval quality** comparison vector-only vs BM25-only vs hybrid
      (Recall@5 / MRR / nDCG). Ranker mode is a *quality* lever with negligible
      latency impact (latency is dominated by the O(n) candidate scan), so it lives
      with the retrieval-quality work, not here.
- [ ] **Per-stage CPU / memory / DB-pool** instrumentation (the harness records
      coarse server RSS today; add per-stage timing + pool gauges).
- [ ] **Graceful degradation** under injected provider/DB failure as a timed
      scenario (invariant #4 is already covered functionally by the P3.3 chaos
      tests; this would add the latency/throughput view).
- [ ] **10k+ store** retrieval on the ANN path (the in-memory linear scan is the
      wrong backend to push to that size).
