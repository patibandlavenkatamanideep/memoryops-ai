"""Worker runtime health endpoint (v0.8, ADR-012)."""

from __future__ import annotations

from app.db.entities import WorkerRunRecord
from app.workers.orchestrator import RUN_COMPLETED, RUN_DEAD_LETTER


def test_workers_health_empty_is_healthy(api_client) -> None:
    client, _repo = api_client
    resp = client.get("/healthz/workers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["healthy"] is True
    assert body["runs_observed"] == 0


def test_workers_health_reflects_dead_letter(api_client) -> None:
    client, repo = api_client
    repo.add_worker_run(
        WorkerRunRecord(tenant_id="t1", user_id="u1", status=RUN_COMPLETED)
    )
    assert client.get("/healthz/workers").json()["healthy"] is True

    repo.add_worker_run(
        WorkerRunRecord(tenant_id="t2", user_id="u2", status=RUN_DEAD_LETTER)
    )
    body = client.get("/healthz/workers").json()
    assert body["healthy"] is False
    assert body["dead_letter_count"] == 1
    assert body["runs_observed"] == 2
