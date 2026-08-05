"""`GET /api/evals/latest` must never execute the harness.

The defect this pins
--------------------
`latest` served a cached result and regenerated it whenever the process cache was
cold or older than `evals_cache_ttl_seconds`. So a caller holding only `evals:read`
could cause real evaluation runs — bounded by the TTL, but real. That collapses the
`evals:read` / `evals:run` split those two permissions exist to express: a TTL limits
how *often* the work happens, it does not make the action a read.

`POST /api/evals/run` is now the only request path that calls the harness, and it is
the path that updates what `latest` serves.
"""

from __future__ import annotations

import pytest

import app.routes.evals as evals_route


@pytest.fixture
def evals_client(monkeypatch):
    """A client with the harness replaced by a counter, so execution is observable."""
    from app import deps
    from app.core import config
    from app.db import factory

    def _clear():
        config.get_settings.cache_clear()
        factory.get_repository.cache_clear()
        deps.gateway.cache_clear()
        deps.audit_service.cache_clear()

    monkeypatch.setenv("MEMORYOPS_STORAGE", "memory")
    _clear()
    evals_route.reset_cache()

    calls = {"n": 0}

    class _Result:
        def to_dict(self):
            calls["n"] += 1
            return {"total": 3, "passed": 3, "failed": 0, "pass_rate": 1.0, "run": calls["n"]}

    def fake_run_evals(*a, **kw):
        return _Result()

    monkeypatch.setattr(evals_route, "run_evals", fake_run_evals)

    from fastapi.testclient import TestClient

    from app.main import app

    yield TestClient(app), calls
    evals_route.reset_cache()
    _clear()


def test_a_cold_read_is_404_and_never_runs_the_harness(evals_client):
    client, calls = evals_client
    r = client.get("/api/evals/latest")
    assert r.status_code == 404
    assert "no_result_available" in r.json()["detail"]
    assert calls["n"] == 0


def test_a_run_executes_once_and_stores_the_result(evals_client, monkeypatch):
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "true")
    from app.core import config

    config.get_settings.cache_clear()

    client, calls = evals_client
    r = client.post("/api/evals/run")
    assert r.status_code == 200, r.text
    assert calls["n"] == 1
    assert r.json()["pass_rate"] == 1.0
    assert "generated_at" in r.json(), "the stored result records when it was produced"


def test_a_read_after_a_run_returns_the_stored_result_without_executing(
    evals_client, monkeypatch
):
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "true")
    from app.core import config

    config.get_settings.cache_clear()

    client, calls = evals_client
    assert client.post("/api/evals/run").status_code == 200
    assert calls["n"] == 1

    for _ in range(5):
        r = client.get("/api/evals/latest")
        assert r.status_code == 200
        assert r.json()["run"] == 1
    assert calls["n"] == 1, "repeated reads must not execute anything"


def test_a_stale_result_is_still_served_rather_than_regenerated(evals_client, monkeypatch):
    """An old result is still the latest *completed* result.

    Regenerating on staleness is what gave `evals:read` execution authority. Serving
    the old one is honest; the caller can see `generated_at`.
    """
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "true")
    monkeypatch.setenv("MEMORYOPS_EVALS_CACHE_TTL_SECONDS", "0")
    from app.core import config

    config.get_settings.cache_clear()

    client, calls = evals_client
    assert client.post("/api/evals/run").status_code == 200
    assert calls["n"] == 1

    # Age the stored result far past any conceivable TTL.
    evals_route._cached_at = 0.0

    r = client.get("/api/evals/latest")
    assert r.status_code == 200
    assert r.json()["run"] == 1
    assert calls["n"] == 1, "a stale result must not trigger regeneration"


def test_a_disabled_deployment_cannot_run_and_leaves_no_result(evals_client, monkeypatch):
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "false")
    from app.core import config

    config.get_settings.cache_clear()

    client, calls = evals_client
    assert client.post("/api/evals/run").status_code == 403
    assert calls["n"] == 0
    assert client.get("/api/evals/latest").status_code == 404


def test_a_failed_run_does_not_replace_the_stored_result(evals_client, monkeypatch):
    """The stored result is replaced only after a run completes, so a crashing
    harness cannot erase the last known-good evidence."""
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "true")
    from app.core import config

    config.get_settings.cache_clear()

    client, calls = evals_client
    assert client.post("/api/evals/run").status_code == 200
    good = client.get("/api/evals/latest").json()

    def _boom(*a, **kw):
        raise RuntimeError("harness exploded")

    monkeypatch.setattr(evals_route, "run_evals", _boom)
    with pytest.raises(RuntimeError):
        client.post("/api/evals/run")

    assert client.get("/api/evals/latest").json() == good


def test_authorization_precedes_the_cache_lookup(evals_client, monkeypatch):
    """An unauthorized reader must not learn whether a result exists, and must not
    reach the harness even in the cold-cache path."""
    from app import deps
    from app.core import config
    from app.db import factory

    monkeypatch.setenv("MEMORYOPS_AUTH_MODE", "trusted_header")
    config.get_settings.cache_clear()
    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()

    client, calls = evals_client
    hdr = {"X-MemoryOps-Tenant": "acme", "X-MemoryOps-User": "alice"}

    # Cold cache: an authorized caller would see 404; an unauthorized one sees 403,
    # so the refusal does not double as an existence probe.
    r = client.get("/api/evals/latest", headers=hdr)
    assert r.status_code == 403
    assert calls["n"] == 0

    r = client.get("/api/evals/latest", headers={**hdr, "X-MemoryOps-Roles": "auditor"})
    assert r.status_code == 404
    assert calls["n"] == 0
