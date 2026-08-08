"""Redis stays out of the topology until something actually uses it.

Redis was declared in `Settings` (`redis_url`), started by Compose, health-gated by
both the API and the worker (`depends_on: condition: service_healthy`), and listed
as one of five required Railway services. No runtime code ever read it: `redis_url`
was referenced exactly once — its own declaration — and no Redis client was imported
anywhere in the repository.

A declared-but-unused infrastructure dependency is pure cost: another managed
service to pay for, another health check that can fail a deploy, and an
architecture diagram that misleads everyone who reads it.

These tests fail if Redis creeps back in *as configuration*. They are deliberately
not a ban: reinstate it the moment something genuinely uses it (distributed rate
limiting, job queueing, caching, pub/sub, cross-replica coordination) — at which
point a real client import will exist and these tests should be updated to assert
that instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
API_APP = REPO_ROOT / "services" / "api" / "app"


def test_settings_has_no_unused_redis_url():
    from app.core.config import Settings

    assert not hasattr(Settings(), "redis_url"), (
        "redis_url is back in Settings — only add it alongside a real consumer"
    )


def test_no_redis_client_is_imported_anywhere():
    """If this ever fails, Redis is genuinely in use and the tests above should change.

    Import detection moved from substring matching to the AST guard: the previous form
    matched `import redis` inside this module's own docstring, and would have matched
    any comment explaining the removal. It also matched `import redis_notes`. The
    guard resolves the imported module name instead.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from repo_trust_guards import check_no_retired_infrastructure

    findings = [
        f for f in check_no_retired_infrastructure(REPO_ROOT) if "redis" in f.detail
    ]
    assert not findings, "\n".join(str(f) for f in findings)


@pytest.mark.parametrize(
    "relative",
    ["docker-compose.yml", ".env.example"],
)
def test_compose_and_env_do_not_declare_redis(relative):
    path = REPO_ROOT / relative
    if not path.exists():  # pragma: no cover - repo layout guard
        pytest.skip(f"{relative} not present")
    text = path.read_text(encoding="utf-8").lower()
    assert "redis" not in text, (
        f"{relative} declares Redis again — the API and worker were previously "
        "health-gated on a service nothing used"
    )


def test_compose_services_are_the_four_real_ones():
    yaml = pytest.importorskip("yaml")
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    services = set(compose["services"])
    # `benchmark` is opt-in via a Compose profile, not part of the running stack.
    assert services == {"db", "api", "worker", "web", "benchmark"}


def test_deployment_docs_do_not_hardcode_a_migration_range():
    """Migration lists go stale silently and produce an incomplete schema.

    railway.md said `001…007` was "the latest" and railway-env.md said `001…005`,
    while the repository had migrations through `011`. Both must use a glob.
    """
    migrations = sorted((REPO_ROOT / "infra" / "db" / "migrations").glob("*.sql"))
    assert migrations, "no migrations found — has the layout changed?"
    latest = migrations[-1].name

    for doc in ("docs/deployment/railway.md", "docs/deployment/railway-env.md"):
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        assert "infra/db/migrations/*.sql" in text, (
            f"{doc} must tell operators to glob the migrations directory, not "
            f"enumerate a range that goes stale (latest is currently {latest})"
        )
