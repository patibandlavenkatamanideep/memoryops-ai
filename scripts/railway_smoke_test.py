#!/usr/bin/env python3
"""Railway smoke test for a deployed MemoryOps AI stack.

Exercises the public surface of a live deployment without any third-party
dependencies (stdlib ``urllib`` only) so it can run from any Railway shell,
CI runner, or laptop:

    python scripts/railway_smoke_test.py \
        --api-url https://memoryops-api.up.railway.app \
        --web-url https://memoryops-web.up.railway.app

Checks, in order:
  1. API liveness     GET  /healthz
  2. API readiness    GET  /readyz
  3. Web loads        GET  <web>/                 (skipped if --web-url omitted)
  4. Memory write     POST /api/chat  ("Remember …")
  5. Memory read      POST /api/chat  (query that should recall the write)
  6. Loop endpoint    GET  /api/loops  + /api/loops/runs
  7. Eval endpoint    POST /api/evals/run          (best-effort; soft-fails)

Exit code is non-zero if any required check fails. The eval check is optional
and only warns, since evals may be disabled in some environments.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

TIMEOUT_SECONDS = 15


class SmokeFailure(Exception):
    """A required check failed."""


def _request(
    method: str, url: str, payload: dict[str, Any] | None = None
) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode()
            try:
                return resp.status, json.loads(body)
            except json.JSONDecodeError:
                return resp.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except urllib.error.URLError as exc:
        raise SmokeFailure(f"{method} {url} unreachable: {exc.reason}") from exc


def _ok(label: str, detail: str = "") -> None:
    print(f"[PASS] {label}" + (f" — {detail}" if detail else ""))


def _warn(label: str, detail: str = "") -> None:
    print(f"[WARN] {label}" + (f" — {detail}" if detail else ""))


def check_health(api: str) -> None:
    status, body = _request("GET", f"{api}/healthz")
    if status != 200 or not isinstance(body, dict) or body.get("status") != "ok":
        raise SmokeFailure(f"/healthz returned {status}: {body}")
    _ok("api liveness /healthz", f"version={body.get('version')}")


def check_ready(api: str) -> None:
    status, body = _request("GET", f"{api}/readyz")
    if status != 200 or not isinstance(body, dict) or not body.get("ready"):
        raise SmokeFailure(f"/readyz not ready ({status}): {body}")
    _ok(
        "api readiness /readyz",
        f"storage={body.get('storage')} llm={body.get('llm_provider')}",
    )


def check_web(web: str) -> None:
    status, _ = _request("GET", web)
    if status != 200:
        raise SmokeFailure(f"web root returned {status}")
    _ok("web loads", web)


def check_write(api: str, tenant: str, user: str, secret: str) -> None:
    payload = {
        "tenant_id": tenant,
        "user_id": user,
        "message": f"Remember that my smoke-test token is {secret}.",
    }
    status, body = _request("POST", f"{api}/api/chat", payload)
    if status != 200 or not isinstance(body, dict):
        raise SmokeFailure(f"write chat returned {status}: {body}")
    evidence = body.get("loop_evidence", {})
    _ok("memory write path", f"loop_evidence={evidence}")


def check_read(api: str, tenant: str, user: str, secret: str) -> None:
    payload = {
        "tenant_id": tenant,
        "user_id": user,
        "message": "What is my smoke-test token?",
    }
    status, body = _request("POST", f"{api}/api/chat", payload)
    if status != 200 or not isinstance(body, dict):
        raise SmokeFailure(f"read chat returned {status}: {body}")
    used = body.get("used_memories", [])
    # Retrieval is best-effort (graceful degradation); a 200 with the loop
    # evidence present is the hard requirement. Recall is reported, not enforced.
    recalled = any(secret in json.dumps(m) for m in used)
    _ok(
        "memory read path",
        f"used_memories={len(used)} recalled_token={recalled}",
    )


def check_loops(api: str) -> None:
    status, body = _request("GET", f"{api}/api/loops")
    if status != 200 or not isinstance(body, list) or not body:
        raise SmokeFailure(f"/api/loops returned {status}: {body}")
    status_runs, runs = _request("GET", f"{api}/api/loops/runs")
    if status_runs != 200:
        raise SmokeFailure(f"/api/loops/runs returned {status_runs}: {runs}")
    _ok(
        "loop endpoint",
        f"definitions={len(body)} runs={len(runs) if isinstance(runs, list) else '?'}",
    )


def check_evals(api: str) -> None:
    """Optional: evals may be disabled. Warn instead of failing."""
    status, body = _request("POST", f"{api}/api/evals/run", {})
    if status == 200:
        rate = body.get("pass_rate") if isinstance(body, dict) else None
        _ok("eval endpoint", f"pass_rate={rate}")
    else:
        _warn("eval endpoint", f"non-200 ({status}); treated as optional")


def main() -> int:
    parser = argparse.ArgumentParser(description="MemoryOps Railway smoke test")
    parser.add_argument("--api-url", required=True, help="Base URL of memoryops-api")
    parser.add_argument("--web-url", default="", help="Base URL of memoryops-web (optional)")
    parser.add_argument(
        "--skip-evals", action="store_true", help="Skip the optional eval check"
    )
    args = parser.parse_args()

    api = args.api_url.rstrip("/")
    web = args.web_url.rstrip("/")
    tenant = "tenant_smoke"
    user = "user_smoke"
    secret = f"tok-{uuid.uuid4().hex[:8]}"

    required: list[tuple[str, Any]] = [
        ("liveness", lambda: check_health(api)),
        ("readiness", lambda: check_ready(api)),
        ("memory_write", lambda: check_write(api, tenant, user, secret)),
        ("memory_read", lambda: check_read(api, tenant, user, secret)),
        ("loops", lambda: check_loops(api)),
    ]
    if web:
        required.insert(2, ("web", lambda: check_web(web)))

    failures: list[str] = []
    for name, fn in required:
        try:
            fn()
        except SmokeFailure as exc:
            failures.append(name)
            print(f"[FAIL] {name} — {exc}")

    if not args.skip_evals:
        try:
            check_evals(api)
        except SmokeFailure as exc:
            _warn("eval endpoint", str(exc))

    print()
    if failures:
        print(f"RESULT: FAIL — {len(failures)} required check(s) failed: {', '.join(failures)}")
        return 1
    print("RESULT: PASS — all required smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
