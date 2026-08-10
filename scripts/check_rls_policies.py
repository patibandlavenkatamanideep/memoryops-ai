#!/usr/bin/env python3
"""Row-Level Security verifier for MemoryOps AI (v0.3).

Proves the database-level tenant isolation guarantee (ADR-006, invariant #1):

  1. RLS is enabled + forced on the protected tables.
  2. A tenant-isolation policy exists on each.
  3. With app.tenant_id set to tenant A, a query never returns tenant B's rows.

Two modes, deliberately different:

**No-infra mode** — SQLAlchemy missing, or no database reachable. Prints SKIP and
exits 0 so a laptop or a no-infra pipeline is never blocked.

**Real-DB mode** — the database answered. The behavioral probe is then *mandatory*:
if it cannot be provisioned, cannot authenticate, or cannot run, that is a FAIL, not
a warning. A job that reaches a real Postgres and prints PASS must have actually
proven cross-tenant isolation.

That distinction was previously missing. The probe raised, the script printed
``[WARN] behavioral probe skipped`` and returned 0, and the Postgres CI job went
green while proving only that the *structural* policies exist — the leak test itself
never ran. Structure without behaviour is not the guarantee this file claims to make.

Usage:
    python scripts/check_rls_policies.py
    DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db python scripts/check_rls_policies.py
"""

from __future__ import annotations

import os

_PROTECTED = (
    "memory_records",
    "memory_audit_logs",
    "memory_feedback",
    "memory_settings",
    "loop_runs",
    "loop_events",
    "worker_runs",
)
_PROBE_ROLE = "rls_probe_role"
_PROBE_PW = "rls_probe_pw"


def _database_url() -> str:
    return os.getenv("DATABASE_URL") or os.getenv("MEMORYOPS_DATABASE_URL") or (
        "postgresql+psycopg://memoryops:memoryops@localhost:5432/memoryops"
    )


def _probe_url(admin_url: str) -> str:
    """A non-superuser connection URL for the behavioral probe.

    RLS is bypassed by superusers/BYPASSRLS roles, so probing on the admin
    connection would be meaningless. Prefer an explicit MEMORYOPS_RLS_PROBE_URL;
    otherwise derive a non-superuser role on the same database.

    ``render_as_string(hide_password=False)`` is required. ``str(URL)`` and the
    default ``render_as_string()`` mask the password as ``***``, so the DSN carries
    the literal three characters and the probe authenticates with them. Under
    ``trust`` auth that silently works; under ``scram``/``md5`` — i.e. CI — it fails
    with ``password authentication failed for user "rls_probe_role"``, which is
    exactly what the Postgres job was reporting while still passing.
    ``tests/test_rls.py`` had already hit this and documented it; this script had not.
    """
    if (override := os.getenv("MEMORYOPS_RLS_PROBE_URL")):
        return override
    from sqlalchemy.engine import make_url

    return (
        make_url(admin_url)
        .set(username=_PROBE_ROLE, password=_PROBE_PW)
        .render_as_string(hide_password=False)
    )


def _is_superuser(engine) -> bool:
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(text("select current_setting('is_superuser')")).scalar_one() == "on"


def _ensure_probe_engine(engine, url: str, is_super: bool):
    """Return an engine the RLS probe is meaningful on — i.e. a non-superuser role."""
    from sqlalchemy import create_engine, text

    if os.getenv("MEMORYOPS_RLS_PROBE_URL"):
        return create_engine(_probe_url(url), future=True)
    if not is_super:
        return engine  # the admin connection is already a non-superuser
    # Superuser connection: provision a dedicated non-superuser role so RLS applies.
    with engine.begin() as conn:
        exists = conn.execute(
            text("select 1 from pg_roles where rolname = :r"), {"r": _PROBE_ROLE}
        ).scalar()
        if not exists:
            conn.execute(text(f"create role {_PROBE_ROLE} login password '{_PROBE_PW}'"))
        else:
            # Existing is not the same as correct. A role left over from an earlier
            # run may have a different password, or no LOGIN, and the probe would
            # fail to authenticate for a reason that looks like an RLS problem.
            conn.execute(text(f"alter role {_PROBE_ROLE} login password '{_PROBE_PW}'"))
        # Never grant BYPASSRLS or superuser: the probe is only meaningful as a role
        # that RLS actually applies to.
        conn.execute(text(f"alter role {_PROBE_ROLE} nosuperuser nobypassrls"))
        conn.execute(text(f"grant usage on schema public to {_PROBE_ROLE}"))
        for table in _PROTECTED:
            conn.execute(text(f"grant select, insert on {table} to {_PROBE_ROLE}"))
    return create_engine(_probe_url(url), future=True)


def _assert_probe_is_unprivileged(probe_engine) -> None:
    """The probe must run as a role RLS applies to, or it proves nothing.

    A superuser or BYPASSRLS role would read across tenants and be reported as a
    leak — so this cannot mask a real failure. It exists to make the *reason*
    explicit rather than surfacing as a confusing cross-tenant leak.
    """
    from sqlalchemy import text

    with probe_engine.connect() as conn:
        is_super = conn.execute(
            text("select current_setting('is_superuser')")
        ).scalar_one() == "on"
        bypass = conn.execute(
            text("select coalesce(bool_or(rolbypassrls), false) from pg_roles "
                 "where rolname = current_user")
        ).scalar_one()
    if is_super or bypass:
        raise RuntimeError(
            "probe role is privileged (superuser or BYPASSRLS); RLS would be bypassed "
            "and the behavioral proof would be meaningless"
        )


def _seed_probe_row(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("select set_config('app.tenant_id', 'rls_probe_b', true)"))
        conn.execute(text("delete from memory_records where tenant_id = 'rls_probe_b'"))
        conn.execute(text("delete from loop_events where trace_id = 'rls_probe_trace'"))
        conn.execute(text("delete from loop_runs where tenant_id = 'rls_probe_b'"))
        conn.execute(text("delete from worker_runs where tenant_id = 'rls_probe_b'"))
        conn.execute(
            text(
                "insert into memory_records (tenant_id, user_id, memory_type, content, source) "
                "values ('rls_probe_b', 'probe_user', 'preference', 'probe', '{}'::jsonb)"
            )
        )
        conn.execute(
            text(
                "insert into loop_runs "
                "(id, loop_id, trace_id, tenant_id, user_id, status) "
                "values ('rls_probe_loop_b', 'memory.write', 'rls_probe_trace', "
                "'rls_probe_b', 'probe_user', 'running')"
            )
        )
        conn.execute(
            text(
                "insert into loop_events "
                "(id, loop_run_id, loop_id, trace_id, state_to, event_type, reason) "
                "values ('rls_probe_event_b', 'rls_probe_loop_b', 'memory.write', "
                "'rls_probe_trace', 'observed', 'probe', 'probe')"
            )
        )
        conn.execute(
            text(
                "insert into worker_runs (id, tenant_id, user_id, status) "
                "values ('rls_probe_worker_b', 'rls_probe_b', 'probe_user', 'completed')"
            )
        )


def _cleanup_probe_row(engine) -> None:
    from sqlalchemy import text

    try:
        with engine.begin() as conn:
            conn.execute(text("select set_config('app.tenant_id', 'rls_probe_b', true)"))
            conn.execute(text("delete from memory_records where tenant_id = 'rls_probe_b'"))
            conn.execute(text("delete from loop_events where trace_id = 'rls_probe_trace'"))
            conn.execute(text("delete from loop_runs where tenant_id = 'rls_probe_b'"))
            conn.execute(text("delete from worker_runs where tenant_id = 'rls_probe_b'"))
    except Exception:  # noqa: BLE001 — best-effort cleanup
        pass


def main() -> int:
    print("MemoryOps AI — RLS policy check")
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("SKIP: sqlalchemy not installed (no Postgres backend in this environment).")
        return 0

    url = _database_url()
    try:
        engine = create_engine(url, pool_pre_ping=True, future=True)
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001 — DB simply not reachable here
        print(f"SKIP: cannot reach database ({type(exc).__name__}). RLS check not run.")
        return 0

    failures: list[str] = []
    with conn:
        # 1. RLS enabled + forced on each protected table.
        rows = {
            r[0]: (r[1], r[2])
            for r in conn.execute(
                text(
                    "select relname, relrowsecurity, relforcerowsecurity "
                    "from pg_class where relname = any(:names)"
                ),
                {"names": list(_PROTECTED)},
            )
        }
        for table in _PROTECTED:
            if table not in rows:
                failures.append(f"{table}: table not found")
                continue
            enabled, forced = rows[table]
            if not enabled:
                failures.append(f"{table}: row level security not ENABLED")
            elif not forced:
                failures.append(f"{table}: row level security not FORCED")
            else:
                print(f"[OK]   {table}: RLS enabled + forced")

        # 2. A policy exists on each protected table.
        policied = {
            r[0]
            for r in conn.execute(
                text("select tablename from pg_policies where tablename = any(:names)"),
                {"names": list(_PROTECTED)},
            )
        }
        for table in _PROTECTED:
            if table in rows and table not in policied:
                failures.append(f"{table}: no RLS policy defined")
            elif table in policied:
                print(f"[OK]   {table}: tenant-isolation policy present")

    # 3. Behavioral probe (must run as a NON-superuser role, or RLS is bypassed).
    #    Seed a foreign-tenant row as admin, then confirm a probe role scoped to a
    #    different tenant cannot see it.
    is_super = _is_superuser(engine)
    probe_ran = False
    try:
        _seed_probe_row(engine)
        probe_engine = _ensure_probe_engine(engine, url, is_super)
        _assert_probe_is_unprivileged(probe_engine)
        with probe_engine.connect() as pconn:
            pconn.execute(text("select set_config('app.tenant_id', 'rls_probe_a', true)"))
            leak_checks = {
                "memory_records": pconn.execute(
                    text("select count(*) from memory_records where tenant_id = 'rls_probe_b'")
                ).scalar_one(),
                "loop_runs": pconn.execute(
                    text("select count(*) from loop_runs where tenant_id = 'rls_probe_b'")
                ).scalar_one(),
                "loop_events": pconn.execute(
                    text("select count(*) from loop_events where id = 'rls_probe_event_b'")
                ).scalar_one(),
                "worker_runs": pconn.execute(
                    text("select count(*) from worker_runs where tenant_id = 'rls_probe_b'")
                ).scalar_one(),
            }
        probe_ran = True
        leaked = {table: count for table, count in leak_checks.items() if count}
        if leaked:
            failures.append(f"cross-tenant leak under RLS: {leaked}")
        else:
            print("[OK]   behavioral probe: no cross-tenant rows visible (non-superuser role)")
    except Exception as exc:  # noqa: BLE001 — reachable DB: inability to probe IS a failure
        # Fail closed. The database answered, so "could not prove isolation" is a
        # result, not an excuse — this is the branch that used to print a warning and
        # return 0 while the leak test never executed.
        failures.append(
            f"behavioral probe did not execute ({type(exc).__name__}: {exc})"
        )
    finally:
        _cleanup_probe_row(engine)

    if not probe_ran and not failures:
        # Defensive: a future edit must not be able to reach a green result without
        # the probe having run.
        failures.append("behavioral probe did not execute (no result recorded)")

    print()
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        print(f"RESULT: FAIL — {len(failures)} RLS issue(s).")
        return 1
    print("RESULT: PASS — RLS enforced on all protected tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
