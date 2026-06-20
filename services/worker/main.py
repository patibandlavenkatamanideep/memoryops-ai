"""Worker entrypoint.

A simple interval scheduler for the demo. In production this becomes Celery beat
or Temporal schedules (see docs/rollout.md). Import order matters: ``jobs`` puts
the API package on sys.path, after which ``app.db.factory`` resolves to the API.
"""

from __future__ import annotations

import os
import time

from jobs import run_all  # adds services/api to sys.path as a side effect

from app.db.factory import get_repository  # noqa: E402  (resolved via jobs import)

INTERVAL_SECONDS = int(os.getenv("WORKER_INTERVAL_SECONDS", "60"))


def tick() -> None:
    repo = get_repository()
    summary = run_all(repo, tenant_id="tenant_demo", user_id="user_demo")
    print({"event": "worker_tick", **summary}, flush=True)


def main() -> None:
    print({"event": "worker_start", "interval_s": INTERVAL_SECONDS}, flush=True)
    while True:
        try:
            tick()
        except Exception as exc:  # noqa: BLE001
            print({"event": "worker_error", "error": str(exc)}, flush=True)
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
