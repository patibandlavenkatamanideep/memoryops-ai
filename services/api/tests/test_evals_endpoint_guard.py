"""The on-demand eval trigger must not be an unauthenticated compute vector (P0.3).

`POST /api/evals/run` is a denial-of-wallet risk if public. It is OFF by default and
returns 403 unless `MEMORYOPS_PUBLIC_EVALS=true`. `GET /api/evals/latest` always works
(cached) so a demo can still show results without letting anyone trigger runs.
"""

from __future__ import annotations

import app.routes.evals as evals_route


def _client():
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    return TestClient(app)


def test_run_is_forbidden_by_default(monkeypatch):
    monkeypatch.delenv("MEMORYOPS_PUBLIC_EVALS", raising=False)
    resp = _client().post("/api/evals/run")
    assert resp.status_code == 403
    assert "MEMORYOPS_PUBLIC_EVALS" in resp.json()["detail"]


def test_run_allowed_when_opted_in(monkeypatch):
    monkeypatch.setenv("MEMORYOPS_PUBLIC_EVALS", "true")
    resp = _client().post("/api/evals/run")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


def test_latest_is_always_available_and_cached(monkeypatch):
    monkeypatch.delenv("MEMORYOPS_PUBLIC_EVALS", raising=False)
    # Reset the module cache so this test controls regeneration.
    evals_route._cached = None
    evals_route._cached_at = 0.0

    calls = {"n": 0}
    real = evals_route.run_evals

    def counting_run():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(evals_route, "run_evals", counting_run)

    client = _client()
    first = client.get("/api/evals/latest")
    second = client.get("/api/evals/latest")
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] >= 1
    # Within the TTL window the harness runs at most once despite two requests.
    assert calls["n"] == 1
