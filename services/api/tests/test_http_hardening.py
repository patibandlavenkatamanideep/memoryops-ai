"""Body-size cap + rate limiting (P2.4)."""

from __future__ import annotations

import pytest

import app.http_hardening as hardening


@pytest.fixture(autouse=True)
def _fresh_limiter():
    hardening._limiter.reset()
    yield
    hardening._limiter.reset()


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    c = TestClient(app_module().app)
    yield c
    get_settings.cache_clear()


def app_module():
    import app.main as m

    return m


def test_oversized_body_returns_413(client, monkeypatch):
    monkeypatch.setenv("MEMORYOPS_MAX_REQUEST_BYTES", "100")
    from app.core.config import get_settings

    get_settings.cache_clear()
    big = {"tenant_id": "t", "user_id": "u", "message": "x" * 5000}
    resp = client.post("/api/chat", json=big)
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"]


def test_chat_rate_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("MEMORYOPS_RATE_LIMIT_CHAT_PER_MINUTE", "3")
    from app.core.config import get_settings

    get_settings.cache_clear()
    hardening._limiter.reset()
    body = {"tenant_id": "t", "user_id": "u", "message": "hi there"}
    codes = [client.post("/api/chat", json=body).status_code for _ in range(6)]
    assert codes.count(200) == 3
    limited = client.post("/api/chat", json=body)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1


def test_message_over_max_length_is_422(client):
    resp = client.post("/api/chat", json={"tenant_id": "t", "user_id": "u", "message": "x" * 9000})
    assert resp.status_code == 422


def test_disabled_rate_limit_allows_burst(client, monkeypatch):
    monkeypatch.setenv("MEMORYOPS_RATE_LIMIT_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    hardening._limiter.reset()
    body = {"tenant_id": "t", "user_id": "u", "message": "hi"}
    codes = [client.post("/api/chat", json=body).status_code for _ in range(20)]
    assert all(c == 200 for c in codes)


def test_sliding_window_limiter_unit():
    lim = hardening.SlidingWindowLimiter(window_seconds=60)
    allowed = [lim.check("k", 2)[0] for _ in range(3)]
    assert allowed == [True, True, False]
    # A different key is independent.
    assert lim.check("other", 2)[0] is True
