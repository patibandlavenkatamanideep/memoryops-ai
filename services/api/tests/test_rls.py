"""Database-level Row-Level Security tests (v0.3, ADR-006).

These prove tenant isolation at the *database* layer (invariant #1, defense in
depth). They require a real Postgres with pgvector and therefore SKIP cleanly
when no database is reachable — so ``pytest -q`` stays infra-free and green.

Crucial detail: **superusers (and BYPASSRLS roles) ignore RLS entirely**, even
with FORCE. The Postgres image used in CI creates POSTGRES_USER as a superuser, so
asserting isolation on that connection would be meaningless. This module therefore
applies the migrations + seeds rows as the (super)user in ``DATABASE_URL``, but
provisions a dedicated *non-superuser* ``app_user`` and runs every isolation
assertion through it — which is the only way the guarantee is real.

Run against a database with, e.g.:
    DATABASE_URL=postgresql+psycopg://memoryops:memoryops@localhost:5432/memoryops \\
        pytest services/api/tests/test_rls.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
pytest.importorskip("pgvector")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

_MIGRATIONS = Path(__file__).resolve().parents[3] / "infra" / "db" / "migrations"
_APP_ROLE = "app_user"
_APP_PW = "app_pw"

_TENANT_A = "rls_tenant_a"
_TENANT_B = "rls_tenant_b"


def _database_url() -> str:
    return os.getenv("DATABASE_URL") or (
        "postgresql+psycopg://memoryops:memoryops@localhost:5432/memoryops"
    )


def _app_url(admin_url: str) -> str:
    """Same database as ``admin_url`` but connecting as the non-superuser app role."""
    return str(make_url(admin_url).set(username=_APP_ROLE, password=_APP_PW))


@pytest.fixture(scope="module")
def admin_engine():
    eng = create_engine(_database_url(), future=True)
    try:
        eng.connect().close()
    except Exception as exc:  # noqa: BLE001 — no DB in this environment
        pytest.skip(f"Postgres not reachable: {type(exc).__name__}")
    return eng


@pytest.fixture
def app_engine(admin_engine):
    """Apply migrations + seed two tenants (as owner), then hand back a
    non-superuser engine RLS actually applies to."""
    # 1. Schema (idempotent — every migration uses IF NOT EXISTS / DROP ... IF EXISTS).
    with admin_engine.begin() as conn:
        conn.execute(text("create extension if not exists vector"))
        for path in sorted(_MIGRATIONS.glob("*.sql")):
            conn.execute(text(path.read_text()))

    # 2. A dedicated non-superuser role RLS is not allowed to bypass.
    with admin_engine.begin() as conn:
        exists = conn.execute(
            text("select 1 from pg_roles where rolname = :r"), {"r": _APP_ROLE}
        ).scalar()
        if not exists:
            conn.execute(text(f"create role {_APP_ROLE} login password '{_APP_PW}'"))
        conn.execute(text(f"grant usage on schema public to {_APP_ROLE}"))
        conn.execute(
            text(f"grant select, insert, update, delete on all tables in schema public to {_APP_ROLE}")
        )

    # 3. Seed one memory row per tenant (as owner — inserts satisfy the schema; the
    #    FKs to tenants/users were dropped in migration 008 to match the app repo).
    with admin_engine.begin() as conn:
        conn.execute(text("delete from memory_records where tenant_id = any(:t)"),
                     {"t": [_TENANT_A, _TENANT_B]})
        for tid in (_TENANT_A, _TENANT_B):
            conn.execute(
                text(
                    "insert into memory_records (tenant_id, user_id, memory_type, content, source) "
                    "values (:t, :u, 'preference', :c, '{}'::jsonb)"
                ),
                {"t": tid, "u": f"user_of_{tid}", "c": f"secret for {tid}"},
            )

    app_eng = create_engine(_app_url(_database_url()), future=True)
    yield app_eng
    app_eng.dispose()
    with admin_engine.begin() as conn:
        conn.execute(text("delete from memory_records where tenant_id = any(:t)"),
                     {"t": [_TENANT_A, _TENANT_B]})


def test_rls_blocks_cross_tenant_query(app_engine):
    with app_engine.begin() as conn:
        conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": _TENANT_A})
        rows = conn.execute(text("select tenant_id from memory_records")).scalars().all()
    assert rows, "tenant A should see its own row"
    assert all(r == _TENANT_A for r in rows)
    assert _TENANT_B not in rows


def test_rls_scopes_each_tenant(app_engine):
    with app_engine.begin() as conn:
        conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": _TENANT_B})
        count_b = conn.execute(text("select count(*) from memory_records")).scalar_one()
    assert count_b == 1


def test_rls_write_check_blocks_foreign_tenant(app_engine):
    """The WITH CHECK clause must forbid writing a row for a different tenant."""
    import sqlalchemy

    with pytest.raises(sqlalchemy.exc.ProgrammingError):
        with app_engine.begin() as conn:
            conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": _TENANT_A})
            conn.execute(
                text(
                    "insert into memory_records (tenant_id, user_id, memory_type, content, source) "
                    "values (:t, 'u', 'preference', 'x', '{}'::jsonb)"
                ),
                {"t": _TENANT_B},  # writing B's row while scoped to A → policy violation
            )


def test_rls_enabled_and_forced(admin_engine):
    with admin_engine.begin() as conn:
        enabled, forced = conn.execute(
            text(
                "select relrowsecurity, relforcerowsecurity from pg_class "
                "where relname = 'memory_records'"
            )
        ).one()
    assert enabled and forced
