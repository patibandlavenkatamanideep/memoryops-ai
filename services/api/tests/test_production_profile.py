"""Production profile guard (v2.3).

``Settings.production_readiness_errors()`` turns every demo-friendly *default*
into a hard error under ``MEMORYOPS_PROFILE=production`` and stays silent when the
settings are actually safe — and ``app.main`` refuses to import when the guard has
violations (fail-closed startup). Dependency-specific readiness is covered
separately in ``test_readiness_probes.py``.
"""

from __future__ import annotations

import subprocess
import sys

from app.core.config import Settings


# ── production readiness guard ───────────────────────────────────────────────
def test_dev_profile_never_errors():
    # The default (demo) profile must boot with zero infra — no violations.
    assert Settings().production_readiness_errors() == []
    assert Settings(storage="memory", auth_mode="none").production_readiness_errors() == []


def test_production_profile_rejects_insecure_defaults():
    errors = Settings(profile="production").production_readiness_errors()
    blob = " ".join(errors).lower()
    # in-memory store, auth off, and open CORS are each independently fatal.
    assert any("storage" in e for e in errors)
    assert any("auth_mode" in e for e in errors)
    assert any("cors" in e for e in errors)
    assert "public_evals" not in blob  # default is already safe


def test_production_profile_flags_demo_creds_and_public_evals():
    errors = Settings(
        profile="production",
        storage="postgres",
        auth_mode="jwt",
        cors_allow_origins="https://app.example.com",
        public_evals=True,
        # still the bundled demo DSN → must be flagged
    ).production_readiness_errors()
    assert any("demo credentials" in e or "localhost" in e for e in errors)
    assert any("public_evals" in e for e in errors)


def test_production_profile_passes_when_hardened():
    safe = Settings(
        profile="production",
        storage="postgres",
        auth_mode="jwt",
        cors_allow_origins="https://app.example.com,https://admin.example.com",
        database_url="postgresql+psycopg://real:secret@db.internal:5432/memoryops",
        public_evals=False,
    )
    assert safe.production_readiness_errors() == []


def test_cors_origins_parsing():
    assert Settings(cors_allow_origins="*").cors_origins_list() == ["*"]
    assert Settings(cors_allow_origins="").cors_origins_list() == ["*"]
    assert Settings(cors_allow_origins="https://a.com, https://b.com").cors_origins_list() == [
        "https://a.com",
        "https://b.com",
    ]


def test_app_refuses_to_import_under_insecure_production_profile():
    """Fail-closed startup: importing app.main with the production profile and
    insecure defaults raises rather than serving traffic."""
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=_api_dir(),
        env={**_env(), "MEMORYOPS_PROFILE": "production"},
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "MEMORYOPS_PROFILE=production" in proc.stderr


def test_app_imports_under_hardened_production_profile():
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main; print('ok')"],
        cwd=_api_dir(),
        env={
            **_env(),
            "MEMORYOPS_PROFILE": "production",
            "MEMORYOPS_STORAGE": "postgres",
            "MEMORYOPS_AUTH_MODE": "trusted_header",
            "MEMORYOPS_CORS_ALLOW_ORIGINS": "https://app.example.com",
            "MEMORYOPS_DATABASE_URL": "postgresql+psycopg://real:secret@db.internal:5432/memoryops",
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


# ── DATABASE_URL fallback precedence ─────────────────────────────────────────
def test_database_url_precedence_is_deterministic(monkeypatch):
    """MEMORYOPS_DATABASE_URL wins; DATABASE_URL is the fallback; neither → default."""
    from app.core import config

    def _load(**env):
        for k in ("MEMORYOPS_DATABASE_URL", "DATABASE_URL"):
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        config.get_settings.cache_clear()
        return config.get_settings().database_url

    try:
        prefixed = "postgresql+psycopg://a:b@memoryops-prefixed/db"
        plain = "postgresql+psycopg://a:b@plain-fallback/db"
        # Both set → the MEMORYOPS_-prefixed knob takes precedence.
        assert _load(MEMORYOPS_DATABASE_URL=prefixed, DATABASE_URL=plain) == prefixed
        # Only the conventional var set → it is honored.
        assert _load(DATABASE_URL=plain) == plain
        # Neither set → the built-in default.
        assert _load() == config.Settings().database_url
    finally:
        config.get_settings.cache_clear()


def _api_dir() -> str:
    import pathlib

    return str(pathlib.Path(__file__).resolve().parents[1])


def _env() -> dict:
    import os

    # Inherit PATH/PYTHONPATH etc. but drop any MEMORYOPS_* the caller set.
    return {k: v for k, v in os.environ.items() if not k.startswith("MEMORYOPS_")}
