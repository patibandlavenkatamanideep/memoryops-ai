#!/usr/bin/env python3
"""MemoryOps AI — HTTP load / performance harness (P4.3).

Drives concurrent HTTP load against a *running* MemoryOps API and records
throughput + latency percentiles + error rate for the three user-facing
operations the review calls out:

    write      a chat message that is a *statement* → extraction + policy +
               store + audit (the full write path).
    retrieval  a chat message that is a *question* against a pre-seeded store →
               retrieve + rank + admission + compose (the read path).
    chat       a representative mixed message (question, may also write).

For each (operation × concurrency) it fires a fixed number of requests through a
thread pool of `concurrency` workers and reports requests/sec, p50/p95/p99 (and
min/mean/max) latency, and the non-2xx error rate. Optionally samples the server
process RSS via `ps` for a coarse memory figure.

What this harness controls for (so concurrency is closer to the only variable)
-----------------------------------------------------------------------------
* **Reused, bounded HTTP clients.** One ``httpx.Client`` is created *per scenario*
  and shared across that scenario's worker threads (with a connection pool bounded
  to the concurrency), then closed. Requests reuse keep-alive connections instead
  of paying fresh client + TCP + TLS setup on every call, so latency reflects the
  server, not client construction.
* **Fresh scope per scenario.** Every scenario runs under a unique
  ``tenant_id``/``user_id``, so store size, duplicate-detection state, and the
  retrieval working set do not accumulate across the sweep.
* **Fixed, identical seed count.** Each scenario's fresh scope is pre-seeded to the
  same ``--seed-per-scenario`` memory count, so the retrieval workload is the same
  in every scenario regardless of order.
* **Repetitions + randomized order.** Each (operation × concurrency) is repeated
  ``--repetitions`` times and the scenarios are run in a randomized order (seeded
  via ``--rng-seed`` for reproducibility), so warm-up drift and ordering effects
  are spread out rather than confounded with a single variable. Aggregates report
  the median across repetitions.
* **Actual memory counts.** Each scenario records the real memory count in its
  scope before and after the run, so store growth is measured, not assumed.

Design notes
------------
* HTTP, not in-process: this is deliberately the realistic path. It exercises
  Starlette's threadpool (the sync route handlers run there).
* Offline + reproducible: default config is in-memory store + stub providers, so
  there are no API keys, no DB, and the numbers are deterministic in shape.
* The harness does not boot the server (server lifecycle differs a lot between a
  laptop and CI); point it at a URL you started with the env you want to measure.
* This harness measures throughput/latency/error behavior under a load pattern.
  It does not, on its own, isolate *why* throughput is flat (client overhead,
  thread-pool limits, CPU/GIL work, or repository growth) — treat the numbers as
  observations of the tested single-process configuration, not a root cause.

Usage
-----
    python benchmark/perf/run_perf.py \
        --base-url http://127.0.0.1:8099 \
        --requests 400 --concurrency 1,5,10,25,50 \
        --repetitions 3 --seed-per-scenario 50 \
        --out results.json

Exit code is 0 unless a scenario exceeds --max-error-rate (default 0.5),
so a smoke run can gate CI.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field

import httpx

# ── request factories ─────────────────────────────────────────────────────────
_STATEMENTS = [
    "Remember that I prefer metric units.",
    "Note that I work in the Pacific timezone.",
    "I like my code reviews to be concise and direct.",
    "My favourite editor is Neovim.",
    "Please keep responses under three sentences when I ask quick questions.",
]
_QUESTIONS = [
    "What are my display and unit preferences?",
    "What timezone do I work in?",
    "How do I like my code reviews?",
    "Which editor do I prefer?",
    "How long should quick answers be?",
]


def _op_body(op: str, tenant: str, user: str, i: int) -> dict:
    if op == "write":
        msg = _STATEMENTS[i % len(_STATEMENTS)] + f" (#{i})"
    elif op == "retrieval":
        msg = _QUESTIONS[i % len(_QUESTIONS)]
    else:  # chat / mixed
        msg = (_QUESTIONS if i % 2 else _STATEMENTS)[i % len(_STATEMENTS)]
    return {"tenant_id": tenant, "user_id": user, "message": msg}


# ── metrics ───────────────────────────────────────────────────────────────────
def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


@dataclass
class ScenarioResult:
    operation: str
    concurrency: int
    repetition: int
    n: int
    errors: int
    error_rate: float
    wall_s: float
    rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    mean_ms: float
    max_ms: float
    seed_count: int
    memories_before: int | None
    memories_after: int | None
    status_counts: dict = field(default_factory=dict)


def _run_scenario(
    client: httpx.Client,
    op: str,
    concurrency: int,
    n: int,
    repetition: int,
    tenant: str,
    user: str,
    seed_count: int,
    memories_before: int | None,
) -> ScenarioResult:
    """Fire `n` requests for `op` through `concurrency` workers on a shared client."""
    latencies: list[float] = []
    statuses: dict[str, int] = {}
    errors = 0

    def _one(i: int) -> tuple[float, int]:
        body = _op_body(op, tenant, user, i)
        t0 = time.perf_counter()
        try:
            r = client.post("/api/chat", json=body)
            code = r.status_code
        except Exception:  # noqa: BLE001 — count transport errors as failures
            code = 0
        return (time.perf_counter() - t0) * 1000.0, code

    t_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_one, i) for i in range(n)]
        for f in as_completed(futures):
            ms, code = f.result()
            latencies.append(ms)
            key = str(code)
            statuses[key] = statuses.get(key, 0) + 1
            if not (200 <= code < 300):
                errors += 1
    wall = time.perf_counter() - t_start

    latencies.sort()
    return ScenarioResult(
        operation=op,
        concurrency=concurrency,
        repetition=repetition,
        n=n,
        errors=errors,
        error_rate=errors / n if n else 0.0,
        wall_s=round(wall, 4),
        rps=round(n / wall, 1) if wall else 0.0,
        p50_ms=round(_pct(latencies, 0.50), 3),
        p95_ms=round(_pct(latencies, 0.95), 3),
        p99_ms=round(_pct(latencies, 0.99), 3),
        min_ms=round(latencies[0], 3),
        mean_ms=round(statistics.fmean(latencies), 3),
        max_ms=round(latencies[-1], 3),
        seed_count=seed_count,
        memories_before=memories_before,
        memories_after=None,  # filled in by the caller after the run
        status_counts=statuses,
    )


# ── scope helpers ─────────────────────────────────────────────────────────────
def _seed_scope(client: httpx.Client, tenant: str, user: str, count: int) -> None:
    """Populate `tenant`/`user` with `count` memories via write-path chat messages."""
    for i in range(count):
        client.post(
            "/api/chat",
            json={
                "tenant_id": tenant,
                "user_id": user,
                "message": f"Remember fact number {i}: item_{i} has value {i * 7 % 97}.",
            },
        )


def _memory_count(client: httpx.Client, tenant: str, user: str) -> int | None:
    """Actual active-memory count in a scope (best-effort; None on failure)."""
    try:
        r = client.get("/api/memories", params={"tenant_id": tenant, "user_id": user})
        if r.status_code == 200:
            data = r.json()
            return len(data) if isinstance(data, list) else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _bounded_client(base_url: str, concurrency: int, timeout: float) -> httpx.Client:
    """A reused client whose connection pool is bounded to the concurrency level."""
    keep = max(concurrency, 1)
    limits = httpx.Limits(max_connections=keep, max_keepalive_connections=keep)
    return httpx.Client(base_url=base_url, timeout=timeout, limits=limits)


def _server_rss_mb(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5
        )
        return round(int(out.stdout.strip()) / 1024.0, 1)
    except Exception:  # noqa: BLE001
        return None


# ── aggregation ───────────────────────────────────────────────────────────────
def _aggregate(results: list[ScenarioResult]) -> list[dict]:
    """Median across repetitions for each (operation, concurrency)."""
    groups: dict[tuple[str, int], list[ScenarioResult]] = {}
    for r in results:
        groups.setdefault((r.operation, r.concurrency), []).append(r)

    agg: list[dict] = []
    for (op, conc), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        med = lambda vals: round(statistics.median(vals), 3)  # noqa: E731
        agg.append(
            {
                "operation": op,
                "concurrency": conc,
                "repetitions": len(rs),
                "rps_median": med([r.rps for r in rs]),
                "p50_ms_median": med([r.p50_ms for r in rs]),
                "p95_ms_median": med([r.p95_ms for r in rs]),
                "p99_ms_median": med([r.p99_ms for r in rs]),
                "error_rate_max": round(max(r.error_rate for r in rs), 4),
            }
        )
    return agg


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8099")
    ap.add_argument("--requests", type=int, default=400, help="requests per scenario")
    ap.add_argument("--concurrency", default="1,5,10,25,50")
    ap.add_argument("--operations", default="write,retrieval,chat")
    ap.add_argument("--warmup", type=int, default=20, help="throwaway warmup requests")
    ap.add_argument(
        "--repetitions", type=int, default=3, help="times to repeat each (op × concurrency)"
    )
    ap.add_argument(
        "--seed-per-scenario",
        type=int,
        default=50,
        help="fixed memory count seeded into each scenario's fresh scope",
    )
    ap.add_argument(
        "--no-randomize",
        action="store_true",
        help="run scenarios in fixed order (default: randomized)",
    )
    ap.add_argument("--rng-seed", type=int, default=1234, help="seed for scenario shuffling")
    ap.add_argument("--server-pid", type=int, default=None, help="sample this pid's RSS")
    ap.add_argument("--label", default="in-memory/stub", help="config label for the report")
    ap.add_argument("--max-error-rate", type=float, default=0.5)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    concurrencies = [int(x) for x in args.concurrency.split(",") if x]
    operations = [x.strip() for x in args.operations.split(",") if x.strip()]

    # health check
    with httpx.Client(base_url=args.base_url, timeout=10.0) as c:
        r = c.get("/healthz")
        r.raise_for_status()
        print(f"server ok: {r.json()}")

    # warmup (not recorded) against a throwaway scope, to warm the server + pool
    if args.warmup:
        wu_tenant, wu_user = "t_warmup", f"u_{uuid.uuid4().hex[:6]}"
        with _bounded_client(args.base_url, max(concurrencies), 30.0) as c:
            for i in range(args.warmup):
                c.post("/api/chat", json=_op_body("chat", wu_tenant, wu_user, i))

    # Build the full scenario list (op × concurrency × repetition) and randomize.
    scenarios = [
        (op, conc, rep)
        for op in operations
        for conc in concurrencies
        for rep in range(args.repetitions)
    ]
    if not args.no_randomize:
        random.Random(args.rng_seed).shuffle(scenarios)

    rss_before = _server_rss_mb(args.server_pid)
    results: list[ScenarioResult] = []
    for op, conc, rep in scenarios:
        # Fresh scope per scenario so store size / dup state / retrieval set do not
        # accumulate across the sweep.
        tenant = f"t_perf_{uuid.uuid4().hex[:8]}"
        user = f"u_{uuid.uuid4().hex[:8]}"
        client = _bounded_client(args.base_url, conc, 30.0)
        try:
            if args.seed_per_scenario:
                _seed_scope(client, tenant, user, args.seed_per_scenario)
            mem_before = _memory_count(client, tenant, user)
            res = _run_scenario(
                client, op, conc, args.requests, rep, tenant, user,
                args.seed_per_scenario, mem_before,
            )
            res.memories_after = _memory_count(client, tenant, user)
        finally:
            client.close()
        results.append(res)
        print(
            f"{op:10s} c={conc:<3d} rep={rep} rps={res.rps:<8.1f} "
            f"p50={res.p50_ms:<8.3f} p95={res.p95_ms:<9.3f} p99={res.p99_ms:<9.3f} "
            f"err={res.error_rate:.1%} mem={res.memories_before}->{res.memories_after} "
            f"{res.status_counts}"
        )
    rss_after = _server_rss_mb(args.server_pid)

    aggregates = _aggregate(results)
    print("\naggregates (median across repetitions):")
    for a in aggregates:
        print(
            f"  {a['operation']:10s} c={a['concurrency']:<3d} "
            f"rps={a['rps_median']:<8.1f} p50={a['p50_ms_median']:<8.3f} "
            f"p95={a['p95_ms_median']:<9.3f} p99={a['p99_ms_median']:<9.3f} "
            f"err_max={a['error_rate_max']:.1%}"
        )

    report = {
        "label": args.label,
        "base_url": args.base_url,
        "requests_per_scenario": args.requests,
        "repetitions": args.repetitions,
        "seed_per_scenario": args.seed_per_scenario,
        "randomized": not args.no_randomize,
        "rng_seed": args.rng_seed,
        "server_rss_mb": {"before": rss_before, "after": rss_after},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": [asdict(r) for r in results],
        "aggregates": aggregates,
    }
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2)
        print(f"wrote {args.out}")

    worst = max((r.error_rate for r in results), default=0.0)
    if worst > args.max_error_rate:
        print(f"FAIL: worst error rate {worst:.1%} > {args.max_error_rate:.1%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
