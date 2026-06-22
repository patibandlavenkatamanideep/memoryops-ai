"""Test fixtures — force the in-memory backend and a fresh stack per test."""

from __future__ import annotations

import os

os.environ["MEMORYOPS_STORAGE"] = "memory"

import pytest  # noqa: E402

from app.db.memory_repo import InMemoryRepository  # noqa: E402
from app.services.gateway import Gateway  # noqa: E402


@pytest.fixture
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def gateway(repo: InMemoryRepository) -> Gateway:
    return Gateway(repo)


@pytest.fixture
def api_client():
    """FastAPI TestClient backed by a fresh in-memory repo singleton.

    The route handlers, gateway, and audit service all resolve the same
    ``get_repository()`` singleton, so we clear the lru_caches to isolate
    state per test and hand back the live repo for seeding/assertions.
    """
    from fastapi.testclient import TestClient

    from app import deps
    from app.db import factory

    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()

    from app.main import app

    repo = factory.get_repository()
    with TestClient(app) as client:
        yield client, repo

    factory.get_repository.cache_clear()
    deps.gateway.cache_clear()
    deps.audit_service.cache_clear()
