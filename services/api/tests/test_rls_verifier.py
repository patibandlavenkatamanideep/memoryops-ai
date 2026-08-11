"""`scripts/check_rls_policies.py` must fail closed once a database is reachable.

The verifier has two legitimate modes and one illegitimate outcome:

* **no-infra** — no SQLAlchemy, or nothing listening. SKIP + exit 0 keeps laptops and
  no-infra pipelines usable.
* **real-DB** — the database answered. The behavioral probe is then mandatory.
* **illegitimate** — a reachable database, a probe that never ran, and a green exit.

That third case was real. The Postgres CI job printed
``[WARN] behavioral probe skipped (... password authentication failed for user
"rls_probe_role")`` and passed, so it verified only that the RLS *policies exist* —
the cross-tenant leak test itself never executed for as long as that warning was
present.

These tests drive `main()` with a fake SQLAlchemy so they need no database, and
assert **exit codes**, not log text: a message can be reworded, an exit code is the
contract CI actually consumes.
"""

from __future__ import annotations

import sys
import types as pytypes
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_rls_policies as rls  # noqa: E402


# ── fake SQLAlchemy surface ──────────────────────────────────────────────────
class _Result:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)

    def scalar_one(self):
        first = self._rows[0]
        return first[0] if isinstance(first, tuple) else first

    def scalar(self):
        if not self._rows:
            return None
        return self._rows[0][0] if isinstance(self._rows[0], tuple) else self._rows[0]


class _Conn:
    """Answers the handful of queries the verifier makes.

    `is_probe` matters for `is_superuser`: the admin connection is a superuser (which
    is what makes the script provision a dedicated role), while the probe connection
    must not be. Conflating the two made a probe-connection test pass on the
    privileged-role assertion instead of the failure it claimed to exercise.
    """

    def __init__(self, cfg, is_probe=False):
        self.cfg = cfg
        self.is_probe = is_probe

    def execute(self, stmt, params=None):
        q = " ".join(str(stmt).lower().split())
        if "relrowsecurity" in q:
            return _Result([(t, self.cfg["enabled"], self.cfg["forced"]) for t in rls._PROTECTED])
        if "pg_policies" in q:
            return _Result([(t,) for t in rls._PROTECTED] if self.cfg["policies"] else [])
        if "is_superuser" in q:
            super_here = (
                self.cfg.get("probe_is_super", False) if self.is_probe else self.cfg["is_super"]
            )
            return _Result([("on" if super_here else "off",)])
        if "rolbypassrls" in q:
            return _Result([(self.cfg.get("probe_bypassrls", False),)])
        if "from pg_roles" in q:
            return _Result([(1,)] if self.cfg.get("role_exists") else [])
        if q.startswith("select count(*)"):
            return _Result([(1 if self.cfg["leak"] else 0,)])
        return _Result([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Engine:
    """`is_probe` matters: the admin connection must stay usable.

    An earlier version of this fake raised on *every* connect, so `main()` took the
    "cannot reach database" path and skipped — testing the no-infra branch while
    claiming to test the probe branch.
    """

    def __init__(self, cfg, is_probe=False):
        self.cfg = cfg
        self.is_probe = is_probe

    def connect(self):
        if self.is_probe and self.cfg.get("probe_connect_raises"):
            raise RuntimeError('password authentication failed for user "rls_probe_role"')
        return _Conn(self.cfg, is_probe=self.is_probe)

    def begin(self):
        return _Conn(self.cfg, is_probe=self.is_probe)


def _install_fake_sqlalchemy(monkeypatch, cfg):
    """Make `from sqlalchemy import ...` inside the script resolve to the fake."""
    sa = pytypes.ModuleType("sqlalchemy")
    sa.text = lambda s: s

    def create_engine(url, **kw):
        if cfg.get("create_engine_raises"):
            raise RuntimeError("boom")
        # The probe engine is the one built from the derived probe URL.
        return _Engine(cfg, is_probe=rls._PROBE_ROLE in str(url))

    sa.create_engine = create_engine

    engine_mod = pytypes.ModuleType("sqlalchemy.engine")

    class _URL:
        """Faithful enough that the derived probe DSN really names the probe role.

        A no-op `set()` made `_probe_url()` return the admin DSN, so the fake could
        not tell the probe engine from the admin one.
        """

        def __init__(self, s, username="u", password="pw"):
            self.s = s
            self.username = username
            self.password = password

        def set(self, username=None, password=None, **kw):
            return _URL(self.s, username or self.username, password or self.password)

        def render_as_string(self, hide_password=True):
            pw = "***" if hide_password else self.password
            return f"postgresql+psycopg://{self.username}:{pw}@localhost:5432/d"

    engine_mod.make_url = _URL
    sa.engine = engine_mod

    monkeypatch.setitem(sys.modules, "sqlalchemy", sa)
    monkeypatch.setitem(sys.modules, "sqlalchemy.engine", engine_mod)


def _cfg(**over):
    base = {
        "enabled": True, "forced": True, "policies": True,
        "is_super": False, "leak": False, "role_exists": False,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("MEMORYOPS_RLS_PROBE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:pw@localhost:5432/d")


# ── no-infra mode may skip ───────────────────────────────────────────────────
def test_missing_sqlalchemy_skips_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "sqlalchemy", None)

    def _raise(*a, **k):
        raise ImportError("no sqlalchemy")

    monkeypatch.setattr(rls, "main", rls.main)  # keep reference
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "sqlalchemy":
            raise ImportError("no sqlalchemy")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert rls.main() == 0
    assert "SKIP" in capsys.readouterr().out


def test_unreachable_database_skips_and_exits_zero(monkeypatch, capsys):
    _install_fake_sqlalchemy(monkeypatch, _cfg(create_engine_raises=True))
    assert rls.main() == 0
    assert "SKIP" in capsys.readouterr().out


# ── real-DB mode must fail closed ────────────────────────────────────────────
def test_structural_gap_fails(monkeypatch):
    """RLS enabled but not FORCED is a policy gap, not a warning."""
    _install_fake_sqlalchemy(monkeypatch, _cfg(forced=False))
    assert rls.main() == 1


def test_missing_policy_fails(monkeypatch):
    _install_fake_sqlalchemy(monkeypatch, _cfg(policies=False))
    assert rls.main() == 1


def test_probe_that_cannot_connect_fails(monkeypatch, capsys):
    """The regression this file exists for.

    A reachable database plus an unauthenticable probe role used to print
    `[WARN] behavioral probe skipped` and return 0.
    """
    _install_fake_sqlalchemy(monkeypatch, _cfg(is_super=True, probe_connect_raises=True))
    rc = rls.main()
    out = capsys.readouterr().out
    assert rc == 1, "a probe that never ran must not pass"
    assert "behavioral probe did not execute" in out
    assert "WARN" not in out, "a reachable DB must not downgrade this to a warning"


def test_cross_tenant_leak_fails(monkeypatch, capsys):
    _install_fake_sqlalchemy(monkeypatch, _cfg(leak=True))
    assert rls.main() == 1
    assert "cross-tenant leak" in capsys.readouterr().out


def test_privileged_probe_role_fails(monkeypatch, capsys):
    """A BYPASSRLS probe proves nothing; say so explicitly."""
    _install_fake_sqlalchemy(monkeypatch, _cfg(probe_bypassrls=True))
    assert rls.main() == 1
    assert "behavioral probe did not execute" in capsys.readouterr().out


# ── the healthy path ─────────────────────────────────────────────────────────
def test_valid_non_superuser_probe_passes(monkeypatch, capsys):
    _install_fake_sqlalchemy(monkeypatch, _cfg())
    rc = rls.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "behavioral probe: no cross-tenant rows visible" in out
    assert "RESULT: PASS" in out


# ── the root cause, pinned ───────────────────────────────────────────────────
def test_probe_url_preserves_the_password():
    """`str(URL)` masks the password as `***`; the probe then authenticates with it.

    Harmless under `trust`, a hard failure under `scram`/`md5` — i.e. CI, where it
    produced `password authentication failed for user "rls_probe_role"` while the
    job still passed. Verified against real SQLAlchemy, not the fake.
    """
    pytest.importorskip("sqlalchemy")
    from sqlalchemy.engine import make_url

    admin = "postgresql+psycopg://admin:adminpw@localhost:5432/db"
    derived = rls._probe_url(admin)
    assert make_url(derived).password == rls._PROBE_PW
    assert "***" not in derived
    assert make_url(derived).username == rls._PROBE_ROLE
    # The old construction, for contrast — this is what regressed.
    masked = str(make_url(admin).set(username=rls._PROBE_ROLE, password=rls._PROBE_PW))
    assert make_url(masked).password == "***"


def test_probe_role_constants_are_unprivileged_by_contract():
    """The provisioning SQL must never grant superuser or BYPASSRLS."""
    source = (REPO_ROOT / "scripts" / "check_rls_policies.py").read_text(encoding="utf-8")
    lowered = source.lower()
    assert "nosuperuser nobypassrls" in lowered
    for forbidden in ("create role rls_probe_role login superuser", "with bypassrls"):
        assert forbidden not in lowered
