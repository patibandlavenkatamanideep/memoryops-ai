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


def test_workers_health_fails_closed_when_operational_access_unconfigured(
    api_client, monkeypatch
) -> None:
    """v2.3 (P0, ADR-027): global worker health reads a *cross-tenant* operational
    connection. When it is not configured the surface degrades to an actionable,
    non-fatal state — never a 500, never a falsely-healthy empty view, never a
    fallback onto the tenant-scoped RLS connection."""
    import app.workers.orchestrator as orch
    from app.db.entities import OperationalAccessUnavailable

    client, _repo = api_client

    def _unconfigured(*_a, **_k):
        raise OperationalAccessUnavailable("no operational role configured")

    monkeypatch.setattr(orch, "summarize_runtime_health", _unconfigured)

    body = client.get("/healthz/workers").json()
    assert body["healthy"] is None  # not True (falsely healthy) and not False (crash)
    assert body["detail"] == "operational access not configured"
