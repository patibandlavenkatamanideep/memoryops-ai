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

Design notes
------------
* HTTP, not in-process: this is deliberately the realistic path. It exercises
  Starlette's threadpool (the sync route handlers run there), so it can actually
  *observe* the serialization / saturation the async-decision-rule keys on.
* Offline + reproducible: default config is in-memory store + stub providers, so
  there are no API keys, no DB, and the numbers are deterministic in shape.
* The harness does not boot the server (server lifecycle differs a lot between a
  laptop and CI); point it at a URL you started with the env you want to measure.

Usage
-----
    python benchmark/perf/run_perf.py \
        --base-url http://127.0.0.1:8099 \
        --requests 400 --concurrency 1,5,10,25,50 \
        --out results.json

Exit code is 0 unless a scenario exceeds --max-error-rate (default 0.5),
so a smoke run can gate CI.
"""

from __future__ import annotations

import argparse
import json
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
    status_counts: dict = field(default_factory=dict)


def _run_scenario(
    client_factory,
    op: str,
    concurrency: int,
    n: int,
    tenant: str,
    user: str,
) -> ScenarioResult:
    latencies: list[float] = []
    statuses: dict[str, int] = {}
    errors = 0

    def _one(i: int) -> tuple[float, int]:
        client = client_factory()
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
        status_counts=statuses,
    )


# ── seeding ───────────────────────────────────────────────────────────────────
def _seed(base_url: str, tenant: str, user: str, count: int) -> None:
    """Populate the store with `count` memories via write-path chat messages."""
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        for i in range(count):
            c.post(
                "/api/chat",
                json={
                    "tenant_id": tenant,
                    "user_id": user,
                    "message": f"Remember fact number {i}: item_{i} has value {i * 7 % 97}.",
                },
            )


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


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8099")
    ap.add_argument("--requests", type=int, default=400, help="requests per scenario")
    ap.add_argument("--concurrency", default="1,5,10,25,50")
    ap.add_argument("--operations", default="write,retrieval,chat")
    ap.add_argument("--warmup", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0, help="pre-seed N memories before running")
    ap.add_argument("--server-pid", type=int, default=None, help="sample this pid's RSS")
    ap.add_argument("--label", default="in-memory/stub", help="config label for the report")
    ap.add_argument("--max-error-rate", type=float, default=0.5)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    concurrencies = [int(x) for x in args.concurrency.split(",") if x]
    operations = [x.strip() for x in args.operations.split(",") if x.strip()]
    tenant = "t_perf"
    user = f"u_{uuid.uuid4().hex[:6]}"

    def client_factory() -> httpx.Client:
        # one client per thread-call; cheap for a localhost keep-alive pool
        return httpx.Client(base_url=args.base_url, timeout=30.0)

    # health check
    with httpx.Client(base_url=args.base_url, timeout=10.0) as c:
        r = c.get("/healthz")
        r.raise_for_status()
        print(f"server ok: {r.json()}")

    if args.seed:
        print(f"seeding {args.seed} memories…")
        _seed(args.base_url, tenant, user, args.seed)

    # warmup (not recorded)
    if args.warmup:
        with httpx.Client(base_url=args.base_url, timeout=30.0) as c:
            for i in range(args.warmup):
                c.post("/api/chat", json=_op_body("chat", tenant, user, i))

    rss_before = _server_rss_mb(args.server_pid)
    results: list[ScenarioResult] = []
    for op in operations:
        for conc in concurrencies:
            res = _run_scenario(client_factory, op, conc, args.requests, tenant, user)
            results.append(res)
            print(
                f"{op:10s} c={conc:<3d} rps={res.rps:<8.1f} "
                f"p50={res.p50_ms:<8.3f} p95={res.p95_ms:<9.3f} p99={res.p99_ms:<9.3f} "
                f"err={res.error_rate:.1%} {res.status_counts}"
            )
    rss_after = _server_rss_mb(args.server_pid)

    report = {
        "label": args.label,
        "base_url": args.base_url,
        "requests_per_scenario": args.requests,
        "seed": args.seed,
        "server_rss_mb": {"before": rss_before, "after": rss_after},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": [asdict(r) for r in results],
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
