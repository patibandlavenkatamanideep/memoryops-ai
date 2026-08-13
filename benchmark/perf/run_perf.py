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

What makes a scenario *evidence*
--------------------------------
The harness fails closed rather than emitting a plausible-looking number for a run
that measured something else:

* **Latency is success-only.** p50/p95/p99/min/mean/max come from 2xx requests
  alone. A failed request's duration says how fast the server gave up, which is a
  different quantity; mixing them yields a number that describes neither. Failure
  latency is reported separately as `failed_p50_ms`.
* **Throughput is split.** `attempted_rps` is offered load; `successful_rps` is
  useful work completed and is the canonical figure. Refusals are fast, so counting
  them as throughput makes a server look faster the more work it declines.
* **HTTP 429 invalidates a scenario.** A rate-limited run can sit far below
  `--max-error-rate` while its latency and throughput describe the limiter instead
  of the request path. Measuring the limiter deliberately is legitimate and needs
  `--rate-limit-mode`, which labels the artifact accordingly.
* **No successes means no latency.** Percentiles are `null`, not 0.0, so an
  entirely-failed scenario cannot read as the fastest one in the sweep.

Invalid scenarios exit non-zero (2) and are excluded from the aggregate medians.

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
* **Fixed, identical seed request count.** Each scenario's fresh scope receives the
  same number of ``--seed-per-scenario`` seeding *requests*, so the retrieval
  workload is set up identically regardless of order. A seed message is not
  guaranteed to produce a memory — the policy broker decides — so the resulting
  store size is measured and reported as ``memories_before`` rather than assumed
  equal to the request count.
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

Exit codes: 0 on success, 2 if any scenario is invalid as evidence (rate-limited, or
no successful requests), 1 if a scenario exceeds --max-error-rate (default 0.5) — so
a smoke run can gate CI.
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
def _fmt(value: float | None) -> str:
    """Render a metric, making "no data" visibly different from a fast result."""
    return "n/a" if value is None else f"{value:.3f}"


def _pct(sorted_vals: list[float], p: float) -> float | None:
    """Linear-interpolated percentile, or ``None`` when there is no distribution.

    Returning ``None`` rather than 0.0 is deliberate: a scenario where every request
    failed has no latency, and 0.0 renders as the best possible result.
    """
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


#: A scenario carrying any of these is not performance evidence. 429 means the
#: limiter answered instead of the request path, and its latency describes how fast
#: the server can decline work — see `--rate-limit-mode` to measure that on purpose.
RATE_LIMITED_STATUS = 429


@dataclass
class ScenarioResult:
    operation: str
    concurrency: int
    repetition: int
    n: int  # requests attempted
    successes: int
    errors: int
    error_rate: float
    wall_s: float
    #: Offered load, including work the server refused. Never a measure of capacity.
    attempted_rps: float
    #: Canonical throughput: useful work completed per second.
    successful_rps: float
    #: Back-compatible alias of ``successful_rps`` so older readers of these artifacts
    #: keep working. It was previously computed from *all* requests, which counted
    #: refusals as throughput.
    rps: float
    #: Latency percentiles over successful (2xx) requests only. ``None`` when a
    #: scenario had no successes — reporting 0.0 there would read as "infinitely
    #: fast" for a scenario that in fact completed nothing.
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    min_ms: float | None
    mean_ms: float | None
    max_ms: float | None
    #: Failure latency, kept strictly separate so it can never move a percentile above.
    failed_n: int
    failed_p50_ms: float | None
    rate_limited: int
    #: False when the scenario is not usable as performance evidence.
    valid: bool
    invalid_reason: str | None
    #: Number of seeding *requests* issued, not memories created — a seed message is
    #: not guaranteed to produce a memory. ``memories_before`` is the authoritative
    #: resulting store size.
    seed_requests: int
    #: Retained under its original name for artifact compatibility; same value.
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
    *,
    rate_limit_mode: bool = False,
) -> ScenarioResult:
    """Fire `n` requests for `op` through `concurrency` workers on a shared client.

    Successful and failed latencies are kept apart from the moment they are recorded.
    A failed request's duration describes how quickly the server gave up, which is a
    different quantity from how long the work takes; averaging the two produces a
    number that is neither.
    """
    ok_latencies: list[float] = []
    failed_latencies: list[float] = []
    statuses: dict[str, int] = {}
    errors = 0
    rate_limited = 0

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
            key = str(code)
            statuses[key] = statuses.get(key, 0) + 1
            if 200 <= code < 300:
                ok_latencies.append(ms)
            else:
                failed_latencies.append(ms)
                errors += 1
                if code == RATE_LIMITED_STATUS:
                    rate_limited += 1
    wall = time.perf_counter() - t_start

    ok_latencies.sort()
    failed_latencies.sort()
    successes = len(ok_latencies)

    def _round(value: float | None) -> float | None:
        return None if value is None else round(value, 3)

    valid, invalid_reason = True, None
    if rate_limited and not rate_limit_mode:
        # Fail closed: the limiter answered, so this is not request-path evidence.
        valid = False
        invalid_reason = (
            f"{rate_limited} rate-limited (HTTP {RATE_LIMITED_STATUS}) response(s); "
            "disable the limiter for performance runs, or pass --rate-limit-mode to "
            "measure the limiter deliberately"
        )
    elif successes == 0 and not rate_limit_mode:
        # A fully-rejected run is the *expected* result when deliberately measuring a
        # saturated limiter, so it only invalidates an ordinary performance scenario.
        # The latency percentiles stay null either way — there is still no distribution.
        valid = False
        invalid_reason = "no successful requests; no latency distribution exists"

    return ScenarioResult(
        operation=op,
        concurrency=concurrency,
        repetition=repetition,
        n=n,
        successes=successes,
        errors=errors,
        error_rate=errors / n if n else 0.0,
        wall_s=round(wall, 4),
        attempted_rps=round(n / wall, 1) if wall else 0.0,
        successful_rps=round(successes / wall, 1) if wall else 0.0,
        rps=round(successes / wall, 1) if wall else 0.0,
        p50_ms=_round(_pct(ok_latencies, 0.50)),
        p95_ms=_round(_pct(ok_latencies, 0.95)),
        p99_ms=_round(_pct(ok_latencies, 0.99)),
        min_ms=_round(ok_latencies[0] if ok_latencies else None),
        mean_ms=_round(statistics.fmean(ok_latencies) if ok_latencies else None),
        max_ms=_round(ok_latencies[-1] if ok_latencies else None),
        failed_n=len(failed_latencies),
        failed_p50_ms=_round(_pct(failed_latencies, 0.50)),
        rate_limited=rate_limited,
        valid=valid,
        invalid_reason=invalid_reason,
        seed_requests=seed_count,
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
    """Median across repetitions for each (operation, concurrency).

    Only *valid* repetitions contribute to the latency/throughput medians. An
    invalid scenario has no meaningful distribution, and letting one into the median
    would launder it into the headline number. The invalid count stays visible so a
    partially-invalid group cannot be mistaken for a clean one.
    """
    groups: dict[tuple[str, int], list[ScenarioResult]] = {}
    for r in results:
        groups.setdefault((r.operation, r.concurrency), []).append(r)

    def med(vals: list[float | None]) -> float | None:
        present = [v for v in vals if v is not None]
        return round(statistics.median(present), 3) if present else None

    agg: list[dict] = []
    for (op, conc), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        usable = [r for r in rs if r.valid]
        agg.append(
            {
                "operation": op,
                "concurrency": conc,
                "repetitions": len(rs),
                "valid_repetitions": len(usable),
                "invalid_repetitions": len(rs) - len(usable),
                "attempted_rps_median": med([r.attempted_rps for r in usable]),
                "successful_rps_median": med([r.successful_rps for r in usable]),
                # Back-compatible alias; now success-only, like the field it mirrors.
                "rps_median": med([r.successful_rps for r in usable]),
                "p50_ms_median": med([r.p50_ms for r in usable]),
                "p95_ms_median": med([r.p95_ms for r in usable]),
                "p99_ms_median": med([r.p99_ms for r in usable]),
                "error_rate_max": round(max(r.error_rate for r in rs), 4),
                "rate_limited_total": sum(r.rate_limited for r in rs),
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
        help=(
            "seed *requests* issued into each scenario's fresh scope (not a guaranteed "
            "memory count — see memories_before for the resulting store size)"
        ),
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
    ap.add_argument(
        "--rate-limit-mode",
        action="store_true",
        help=(
            "measure the RATE LIMITER on purpose: HTTP 429 stops invalidating a "
            "scenario. Results are limiter behaviour, not request-path performance"
        ),
    )
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
                rate_limit_mode=args.rate_limit_mode,
            )
            res.memories_after = _memory_count(client, tenant, user)
        finally:
            client.close()
        results.append(res)
        print(
            f"{op:10s} c={conc:<3d} rep={rep} "
            f"ok_rps={_fmt(res.successful_rps):<8s} att_rps={_fmt(res.attempted_rps):<8s} "
            f"p50={_fmt(res.p50_ms):<9s} p95={_fmt(res.p95_ms):<9s} p99={_fmt(res.p99_ms):<9s} "
            f"err={res.error_rate:.1%} mem={res.memories_before}->{res.memories_after} "
            f"{res.status_counts}"
            + ("" if res.valid else f"  INVALID: {res.invalid_reason}")
        )
    rss_after = _server_rss_mb(args.server_pid)

    aggregates = _aggregate(results)
    print("\naggregates (median across VALID repetitions; latency = successful requests only):")
    for a in aggregates:
        suffix = ""
        if a["invalid_repetitions"]:
            suffix = f"  [{a['invalid_repetitions']}/{a['repetitions']} repetitions INVALID]"
        print(
            f"  {a['operation']:10s} c={a['concurrency']:<3d} "
            f"ok_rps={_fmt(a['successful_rps_median']):<8s} "
            f"p50={_fmt(a['p50_ms_median']):<9s} p95={_fmt(a['p95_ms_median']):<9s} "
            f"p99={_fmt(a['p99_ms_median']):<9s} err_max={a['error_rate_max']:.1%}" + suffix
        )

    report = {
        "label": args.label,
        "base_url": args.base_url,
        "requests_per_scenario": args.requests,
        "repetitions": args.repetitions,
        # Seeding *requests*, not a guaranteed memory count; each scenario's
        # `memories_before` is the authoritative resulting store size.
        "seed_requests_per_scenario": args.seed_per_scenario,
        "seed_per_scenario": args.seed_per_scenario,
        "rate_limit_mode": args.rate_limit_mode,
        "latency_basis": "successful (2xx) requests only",
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

    # Fail closed on invalid scenarios *before* the error-rate gate. A rate-limited
    # run can sit under --max-error-rate while its latency and throughput describe
    # refusals rather than work, which is precisely the shape this guard exists to
    # stop from being published as evidence.
    invalid = [r for r in results if not r.valid]
    if invalid:
        print(
            f"FAIL: {len(invalid)}/{len(results)} scenario(s) are not valid performance "
            "evidence:",
            file=sys.stderr,
        )
        for r in invalid:
            print(
                f"  {r.operation} c={r.concurrency} rep={r.repetition}: {r.invalid_reason}",
                file=sys.stderr,
            )
        return 2

    # Under --rate-limit-mode a 429 is the measured outcome, not a fault, so it does
    # not count against the error gate. Every other failure still does — deliberately
    # measuring the limiter must not become a way to tolerate real errors.
    def _gated_error_rate(r: ScenarioResult) -> float:
        counted = r.errors - r.rate_limited if args.rate_limit_mode else r.errors
        return counted / r.n if r.n else 0.0

    worst = max((_gated_error_rate(r) for r in results), default=0.0)
    if worst > args.max_error_rate:
        print(f"FAIL: worst error rate {worst:.1%} > {args.max_error_rate:.1%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
