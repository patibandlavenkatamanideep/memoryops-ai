# Performance (P4.3)

> **Status: characterized on real Postgres + pgvector and a real provider (Phase C).**
> The follow-ups the first pass called for — Postgres/pgvector, a real provider,
> SQL-statement and pool instrumentation — have been run. Their results are in
> [Phase C](#phase-c--real-request-path-characterization) below, with machine-readable
> artifacts in [`benchmark/perf/results/`](../benchmark/perf/results/).
>
> **Everything measured here is a single-node laptop measurement.** It is not a
> Railway figure, not a production throughput number, and not a claim about
> providers other than the one tested.

> **⚠️ Read the numbers below as observations, not proofs.** The tables in this
> document were produced by an **earlier version of the harness** that created a
> fresh, unclosed `httpx.Client` per request and reused a single tenant/user across
> the whole sweep — so client/connection setup cost and a monotonically growing store
> were confounded with concurrency. The harness has since been corrected (reused
> bounded clients, a **fresh scope per scenario**, a **fixed identical seed *request*
> count**, **≥3 repetitions**, **randomized scenario order**, and **actual
> before/after memory counts** — see [`run_perf.py`](../benchmark/perf/run_perf.py)).
> The sweep has since been re-run with the corrected harness on Postgres — see
> [Phase C](#phase-c--real-request-path-characterization), which supersedes the
> figures below. Treat the tables in this section as historical only.
>
> Two further corrections apply to how these numbers were *computed*, so the tables
> below are not directly comparable to output from the current harness:
>
> * **`rps` in these tables counted every request**, including failures. The harness
>   now reports `attempted_rps` and `successful_rps` separately, and `successful_rps`
>   is canonical — refusals are fast, so counting them as throughput rewards a server
>   for declining work.
> * **latency percentiles here included failed requests.** They are now computed from
>   successful (2xx) responses only, with failure latency reported separately. A run
>   containing any HTTP 429 is now rejected outright as performance evidence unless
>   `--rate-limit-mode` is passed, because a rate-limited run measures the limiter
>   rather than the request path.

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
- **Implication for the async decision (P2.1): defer the blanket migration; tune and
  measure the sync path first.** Sync routes already overlap I/O via Starlette's
  threadpool; the stub + in-memory sweep removes the network/DB waiting async targets,
  so it can't settle the question. Keep the sync API + stable 1.x contract, instrument
  and tune the AnyIO thread tokens + SQLAlchemy pool together, and reconsider async only
  when a real-provider + Postgres run shows sustained I/O-bound demand exceeding the
  tuned synchronous architecture. Full verdict + trigger conditions below.
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

It fails closed rather than emitting a plausible number for a run that measured
something else: latency percentiles come from successful requests only, throughput
is split into `attempted_rps` and `successful_rps`, a scenario with no successes
reports `null` latency instead of `0`, and any HTTP 429 invalidates a scenario
(exit code 2) unless `--rate-limit-mode` is passed to measure the limiter
deliberately. `--seed-per-scenario` counts seeding *requests*; the resulting store
size is measured and reported as `memories_before`.

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

### Reproducing the Phase C measurements

Point the same harness at a Postgres-backed server (`MEMORYOPS_STORAGE=postgres`,
`MEMORYOPS_DATABASE_URL=…`) with pgvector installed and the migrations applied.

Two benchmark-only tools support the deeper measurements, both under
`benchmark/perf/` and never imported by `services/api`:

| tool | what it gives you |
|---|---|
| [`sqlprofile.py`](../benchmark/perf/sqlprofile.py) | statements/request, normalized query shapes, per-shape time. Attach with `attach(repo._engine)`. Bound parameters are never captured, so shapes carry no tenant, user, content, embedding or credential. |
| [`provider_accounting.py`](../benchmark/perf/provider_accounting.py) | logical calls vs physical attempts, token/cost accounting, and hard ceilings enforced *before* a request is sent. |

Any live-provider run must call `assert_live_provider_wired()` first. It issues one
request and fails if the provider was not actually called — because `deps.gateway()`
is `lru_cache`d, a rebind after the gateway is built leaves the cached instance on the
old provider, and a stubbed run then produces clean latency numbers and zero provider
calls that look exactly like a successful live run. That happened during Phase C; the
guard exists so it fails loudly instead.

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

> **⚠️ Sections 1–3 are HISTORICAL and SUPERSEDED.** They were produced by the
> earlier harness and the in-memory backend, and their `rps` counted failed requests
> while their percentiles mixed failure latency into success latency. They are kept
> for provenance. For current evidence use
> [Phase C](#phase-c--real-request-path-characterization).

### 1. Concurrency sweep — in-memory / stub / rate-limit off / hybrid ranker *(historical)*

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

### 2. Latency vs store size — retrieval, in-memory (linear scan) *(historical)*

Retrieval p50 as the store grows (single client):

| store size (approx) | retrieval p50 | p95 |
|--------------------:|--------------:|----:|
| 100   | 75.8 ms  | 99.3 ms  |
| 1,000 | 193.2 ms | 321.9 ms |

10× the store → ~2.5× the retrieval latency. Seeding beyond ~1 k memories through
the HTTP write path is **O(n²)** (every seed write also runs a read over the
growing store), so the 5 k / 10 k points were not driven locally — but the trend
above already shows the shape. The in-memory repository scans **O(n)** candidates
per query, so retrieval cost grows with the store. This is a property of the
**dev/default** backend, not of MemoryOps as designed.

> **Correction (Phase C).** An earlier version of this paragraph stated that on
> Postgres "retrieval goes through the pgvector ANN index … which is sub-linear."
> That claim was not measured, and **measurement contradicts it as a general
> statement**. At 100 k total rows with a 10 k-row tenant, the planner did **not**
> choose the IVFFlat index: it used the tenant/status btree, bitmap-heap-scanned all
> 10 000 tenant rows, and top-N sorted them by exact vector distance. IVFFlat *was*
> chosen on a smaller single-tenant dataset. **An index existing is not an index
> being used**, and retrieval on Postgres is not universally ANN or sub-linear —
> the plan is data- and query-dependent. See
> [Phase C](#phase-c--real-request-path-characterization).

Store **memory** also grows with row count — RSS rose from
**37 MB → 234 MB** over the concurrency sweep — but the harness did not record the
exact memory count for those runs, so **no reliable per-memory byte figure can be
derived** from them. (An earlier draft's "~33 KB/memory" divided RSS by an *assumed*
row count and has been removed.) The corrected harness now records actual before/
after memory counts, so a defensible per-memory figure can be measured on the re-run.

### 3. Rate limiter — per-process, fail-fast *(historical)*

`MEMORYOPS_RATE_LIMIT_ENABLED=true`, defaults (chat = 30/min per tenant/IP). A
burst of 100 chat requests (concurrency 10) from one tenant/IP:

| outcome | count |
|---------|------:|
| `200` served | **30** |
| `429` rate-limited | **70** |

Exactly the 30/min cap; rejected requests fail fast (~5 ms). Reproducing this now
requires `--rate-limit-mode` — a burst like this is a limiter measurement, and the
harness refuses to report it as request-path performance. This confirms the
limiter works — **and** confirms the review's caveat: the counter is **in-process**.
Each replica has its own 30/min budget, and a restart resets it. It is **local
process protection, not distributed rate enforcement.** A Redis-backed limiter is
the fix for a real multi-replica limit (follow-up).

## Phase C — real request-path characterization

Measured on **PostgreSQL 17.10 + pgvector 0.8.5** (isolated local cluster, Python
3.13.2), base `0190bcd`. Artifacts:
[`postgres_pgvector_phase-c.json`](../benchmark/perf/results/postgres_pgvector_phase-c.json),
[`postgres_sql_profile_phase-c.json`](../benchmark/perf/results/postgres_sql_profile_phase-c.json),
[`gemini-2.5-flash_phase-c.json`](../benchmark/perf/results/gemini-2.5-flash_phase-c.json).

All numbers below come from the corrected harness: latency is success-only,
throughput is `successful_rps`, and every scenario was valid (0 errors, 0 × 429).

### C1. Local ceiling — Postgres + stub provider

| conc | successful_rps | p50 | p95 | p99 | errors |
|-----:|---------------:|----:|----:|----:|:------:|
| 1  | 42.3 | 21.6 ms   | 28.8 ms   | 31.0 ms   | 0 |
| 5  | 45.7 | 105.5 ms  | 131.5 ms  | 155.6 ms  | 0 |
| 25 | 41.8 | 553.4 ms  | 737.2 ms  | 788.3 ms  | 0 |
| 50 | 40.7 | 1010.1 ms | 1456.6 ms | 1467.3 ms | 0 |

`attempted_rps == successful_rps` throughout. Throughput is flat at ~40 rps from
concurrency 5 upward while latency grows linearly — added concurrency queues rather
than parallelizes. **This ceiling appears with small scopes too**, so it is not
caused by retrieval store size.

### C2. Retrieval latency vs tenant store size

| tenant memories | p50 | p95 |
|----------------:|----:|----:|
| 100    | 26.0 ms | 29.8 ms |
| 1 000  | 31.0 ms | 32.5 ms |
| 10 000 | 87.2 ms | 94.2 ms |

Latency grows with the **tenant's** row count, consistent with the exact top-N sort
in the plan below.

### C3. Query plan — an index existing is not an index being used

At **100 k total rows / 10 k tenant rows**, Postgres did **not** choose IVFFlat:

```
Limit → Sort (top-N heapsort)
  → Bitmap Heap Scan on memory_records (rows=10000)
    → Bitmap Index Scan on idx_memory_user_status
```

That is exact brute-force KNN over the tenant's memories. On a smaller 10 k
single-tenant dataset the same query *did* use `idx_memory_embedding` (IVFFlat),
returning 49/50 rows at the default `ivfflat.probes=1`. The planner's choice is
data- and query-dependent, so **no universal ANN or sub-linear claim holds**.

### C4. SQL statement profile

Measured with [`sqlprofile.py`](../benchmark/perf/sqlprofile.py) via SQLAlchemy
cursor events. Bound parameters are never captured.

| request | statements/request | transactions/request | DB execution/request |
|---|---:|---:|---:|
| read-dominant | **117** (min 117, max 117) | ~73 | 63.3 ms |
| single-candidate write | **130** (min 130, max 130) | — | — |

Per read-dominant request:

| count | ms | shape |
|------:|---:|---|
| **66** | 5.25 | `select set_config(?, ?, true)` |
| 15 | 1.17 | `SELECT loop_runs …` |
| 13 | 1.59 | `SELECT loop_events …` |
| 13 | 1.28 | `INSERT INTO loop_events …` |
| 4 | 0.39 | `INSERT`/`UPDATE loop_runs` |
| **1** | **53.13** | `SELECT memory_records … ORDER BY embedding <=> … LIMIT ?` |
| 4 | 0.41 | audit chain head + `memory_audit_logs` |

Two different things, which must not be conflated: **statement count** is dominated
by `set_config` and loop engineering; **DB time** is dominated by the single
retrieval query (53 ms of 63 ms).

> **On the ~282 `psycopg` `connection.wait` calls per request** seen in an earlier
> CPU profile: the request path is genuinely chatty, but a driver wait is not a SQL
> statement and not a network round trip. The measured figure is **117 statements**,
> i.e. roughly 2.4 waits per statement. *"282 DB round trips per request" is not a
> supported claim.* **GIL causality is likewise NOT PROVEN** — it was never
> separately measured.

**Structural cause (measured, deliberately not changed here).**
`PostgresRepository._scoped()` opens a new `Session` — and therefore a new
transaction — for repository operations outside an explicit `transaction()`,
re-establishing RLS context with two `set_config` statements each. The
loop-engineering layer makes many such calls per request. Consolidating transactions
moves the boundary around RLS context and needs its own Postgres + `FORCE ROW LEVEL
SECURITY` cross-tenant evidence, so it is tracked as a follow-up rather than done
opportunistically.

### C5. DB pool — saturated, but not the bottleneck

Defaults are `pool_size=5` + `max_overflow=10` (15 connections), and peak
connections did reach 15 at high concurrency. A **measurement-only** widening to
~100 raised peak connections to 45 and changed throughput not at all:

| conc | successful_rps @ 15 | successful_rps @ 100 |
|-----:|--------------------:|---------------------:|
| 5  | 43.7 | 44.2 |
| 10 | 39.8 | 40.6 |
| 25 | 40.4 | 40.5 |
| 50 | 39.8 | 38.8 |

Pool saturation was therefore a *symptom*, not the cause. **The widened pool is not
committed.**

### C6. Live provider — Gemini 2.5 Flash

Call shape was verified before spending budget. Workload A is *not* "retrieval-only":
a question still runs extraction.

| workload | conc | requests | successful_rps | p50 | p95 | p99 | logical | physical | retries | errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| A read-dominant / no-candidate chat | 1 | 25 | 1.15 | 820.4 ms | 996.8 ms | 1752.6 ms | 25 | 25 | 0 | 0 |
| A read-dominant / no-candidate chat | 5 | 25 | 5.81 | 833.4 ms | 994.2 ms | 1147.5 ms | 25 | 25 | 0 | 0 |
| B single-candidate write | 1 | 25 | 0.46 | 2196.5 ms | 2564.7 ms | 2675.5 ms | 50 | 50 | 0 | 0 |
| B single-candidate write | 5 | 25 | 2.01 | 2230.2 ms | 3011.6 ms | 3267.9 ms | 50 | 50 | 0 | 0 |

Accepted workload: **100 user-level requests, 150 logical calls, 150 physical
attempts, 0 retries, 0 errors.** Workload B issues two sequential provider calls per
request (extraction + conflict detection), which is why its latency is ~2.7× A's.

**Token accounting is session-level**, covering 152 calls — the 150 workload calls
plus 2 positive wiring-assertion calls. It is not split into a workload-only figure
because the counters were not partitioned at the time:

| | tokens |
|---|---:|
| input | 54 898 |
| output | 6 423 |
| thinking | 10 483 |
| **total** | **71 804** |

Estimated **$0.0587** at assumed rates of $0.30/1M input and $2.50/1M output.
**Thinking tokens are 62 % of billed output** — visible response text badly
understates output billing on this model.

Provider latency dominates: ~820 ms for one call versus 63 ms of DB work per request.

## The async decision (P2.1) — verdict: **defer the blanket migration; tune and measure the synchronous path first**

> **Phase C update — blanket async migration is not justified by the current
> measurements.** Going from concurrency 1 → 5 on the provider-backed path took
> throughput from **1.15 → 5.81 rps while p50 held at 820.4 → 833.4 ms**: the
> synchronous path overlapped provider waiting effectively through the tested
> concurrency. Limitations, stated plainly: only `gemini-2.5-flash` was tested,
> provider-backed concurrency only reached **5**, other providers may behave
> differently, higher concurrency was not measured, and Railway-scale behaviour was
> not measured at all. This is **not** a claim that async can never help.

`POST /api/chat` is a **synchronous** FastAPI route. Starlette executes sync routes
through AnyIO's threadpool, so requests **already overlap** their network and database
waiting time across multiple worker threads — sync is *not* serial.

**Why the current benchmark doesn't settle it.** The default AnyIO limiter provides
**40 shared thread tokens per process** — which is *not* a guaranteed capacity of 40
chat requests: sync dependencies, file operations, background tasks, DB-pool limits,
provider connection limits, CPU work, and other endpoints all draw from the same pool
and can exhaust it sooner. And the in-memory / stub-provider sweep in this doc
**removes the very workload async is designed to improve** — it strips the real network
and DB waiting and emphasizes Python execution, in-memory scans, ranking, and policy
(CPU-bound work async would *not* accelerate, and could slow with added complexity).

**Recommendation (keep the sync API and the stable 1.x contract):**

1. **Instrument** thread-token utilization, request queueing, DB-pool checkout time,
   provider latency, and stage-level CPU time.
2. **Tune AnyIO thread tokens and the SQLAlchemy connection pool together** (raising
   threads without pool headroom just moves the bottleneck).
3. Use **Uvicorn concurrency limits as overload protection**, not as a way to increase
   threadpool capacity.
4. **Move nonessential provider calls off the response-critical path** — particularly
   advisory conflict detection — where possible.
5. **Run the corrected benchmark against Postgres + pgvector and a real LLM + embedding
   provider** (the I/O-bound workload that actually exercises the question).
6. **Reconsider async only** when measurements show sustained I/O-bound demand
   exceeding the tuned synchronous architecture.

**A full async migration becomes justified when:**

- requests spend meaningful time **waiting for available thread tokens**;
- the DB and provider pools have been tuned and are **not** the actual bottleneck;
- sustained target concurrency **exceeds** the safe thread-based capacity;
- increasing threads **materially harms** memory use / context-switching;
- multiple Uvicorn workers or Railway replicas **do not** provide sufficient headroom;
- before/after measurements show async improves throughput or tail latency **enough to
  justify the added complexity**.

**If those conditions are met, migrate incrementally** (each step with before/after
numbers): async provider + embedding clients → async gateway + extraction path →
SQLAlchemy async engine + repository → async routes → explicit offloading for the
CPU-bound ranking / policy / compression / evaluation stages.

Until that evidence exists, a blanket async rewrite is **not** justified.

## Follow-ups (measured next, tracked separately)

Phase C closed the first three of these; each remaining item is a **separate,
measured** change, not an opportunistic edit. In particular, nothing in Phase C
changed runtime application code.

- [x] **Corrected-harness re-run** — done, see [C1](#c1-local-ceiling--postgres--stub-provider).
- [x] **Postgres + pgvector** run — done, see [C1–C4](#phase-c--real-request-path-characterization).
      It also corrected the ANN assumption ([C3](#c3-query-plan--an-index-existing-is-not-an-index-being-used)).
- [x] **Real provider** latency in the hot path — done for `gemini-2.5-flash`
      ([C6](#c6-live-provider--gemini-25-flash)). OpenAI/Anthropic remain unmeasured.

Opened by Phase C, each needing its own evidence:

- [ ] **Repository transaction consolidation** — ~73 transactions and 66 `set_config`
      statements per request. Moves the RLS context boundary, so it requires Postgres
      + `FORCE ROW LEVEL SECURITY` cross-tenant proof before it can land.
- [ ] **Retrieval candidate bounding / query redesign** — one query is 53 ms of the
      63 ms DB time and scales with tenant row count; IVFFlat is not chosen under the
      tenant filter at scale.
- [ ] **Conflict-detection context bounding** — `detect_conflicts` sends *all*
      existing memories untruncated, so write-path prompt size and provider cost grow
      linearly with scope size. This is a cost-correctness issue as much as a
      performance one.
- [ ] **Loop-engineering write volume** — ~43 of the 117 statements per request.
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
