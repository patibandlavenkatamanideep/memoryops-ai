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

import pytest

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
        auth_require_role_claim=True,
    )
    assert safe.production_readiness_errors() == []


# ── provider packaging readiness (fail-closed) ───────────────────────────────
# Every provider adapter imports its SDK lazily and degrades to a stub when the SDK
# or key is missing, so the service starts and looks healthy while serving stub
# output. In production that silent substitution is a hard error instead.
def _hardened(**overrides) -> Settings:
    """A settings object that is production-clean apart from `overrides`."""
    base = dict(
        profile="production",
        storage="postgres",
        auth_mode="jwt",
        cors_allow_origins="https://app.example.com",
        database_url="postgresql+psycopg://real:secret@db.internal:5432/memoryops",
        public_evals=False,
        # Production requires roles to be explicit: a credential with no role claim
        # is refused rather than falling back to the least-privileged default.
        auth_require_role_claim=True,
    )
    return Settings(**{**base, **overrides})


def _all_sdks_present(monkeypatch) -> None:
    """Pretend every optional SDK is installed, isolating key/selection checks."""
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())


def _no_sdks_present(monkeypatch) -> None:
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)


def test_production_rejects_llm_provider_without_api_key(monkeypatch):
    _all_sdks_present(monkeypatch)
    errors = _hardened(llm_provider="openai", openai_api_key="").production_readiness_errors()
    assert any("OPENAI_API_KEY is unset" in e for e in errors)


def test_production_rejects_llm_provider_without_sdk(monkeypatch):
    _no_sdks_present(monkeypatch)
    errors = _hardened(
        llm_provider="anthropic", anthropic_api_key="sk-real"
    ).production_readiness_errors()
    assert any("'anthropic' SDK is not installed" in e for e in errors)
    assert any("memoryops-api[anthropic]" in e for e in errors)


def test_production_gemini_checks_the_module_the_adapter_imports(monkeypatch):
    """The adapter imports `google.genai`, not the retired `google.generativeai`.

    Guards against the extras pinning a package whose module the adapter can't use.
    """
    seen: list[str] = []
    import importlib.util

    def fake(name):
        seen.append(name)
        return object()

    monkeypatch.setattr(importlib.util, "find_spec", fake)
    _hardened(llm_provider="gemini", gemini_api_key="k").production_readiness_errors()
    assert "google.genai" in seen


def test_production_rejects_openai_embeddings_without_key_or_sdk(monkeypatch):
    _all_sdks_present(monkeypatch)
    errors = _hardened(
        embeddings_provider="openai", openai_api_key=""
    ).production_readiness_errors()
    # Embeddings are stricter than the LLM path: a stub vector is *persisted* in the
    # wrong space, so the message must say so.
    assert any("different vector space" in e for e in errors)

    _no_sdks_present(monkeypatch)
    errors = _hardened(
        embeddings_provider="openai", openai_api_key="sk-real"
    ).production_readiness_errors()
    assert any("'openai' SDK is not installed" in e for e in errors)


def test_production_rejects_external_vector_backend_without_client(monkeypatch):
    _no_sdks_present(monkeypatch)
    errors = _hardened(vector_index="qdrant").production_readiness_errors()
    assert any("qdrant_client" in e and "not installed" in e for e in errors)


def test_production_allows_stub_providers_and_memory_index(monkeypatch):
    """The offline default selection must stay clean — no SDKs required."""
    _no_sdks_present(monkeypatch)
    assert _hardened(
        llm_provider="stub", embeddings_provider="stub", vector_index="memory"
    ).production_readiness_errors() == []


def test_production_allows_fully_configured_provider(monkeypatch):
    _all_sdks_present(monkeypatch)
    assert _hardened(
        llm_provider="openai",
        embeddings_provider="openai",
        openai_api_key="sk-real",
        vector_index="qdrant",
    ).production_readiness_errors() == []


def test_provider_checks_are_production_only(monkeypatch):
    """Dev must keep booting with no keys and no SDKs (offline tests, demos)."""
    _no_sdks_present(monkeypatch)
    assert Settings(
        profile="dev", llm_provider="openai", embeddings_provider="openai"
    ).production_readiness_errors() == []


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
            "MEMORYOPS_AUTH_REQUIRE_ROLE_CLAIM": "true",
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


# ── governance ablation must never combine with the production profile ───────
# The research switches (MEMORYOPS_GOVERNANCE_PROFILE=disabled, MEMORYOPS_ABLATE_*)
# ship in the same binary as production so the paper study can measure a governed
# system against a mechanism-matched ungoverned twin. Nothing stopped them being
# combined with MEMORYOPS_PROFILE=production.
#
# Verified before this guard existed: a fully hardened production config plus
# `MEMORYOPS_GOVERNANCE_PROFILE=disabled` produced NO readiness errors, and a live
# API key was stored with status=active — the policy broker's BLOCK never ran.
def test_production_rejects_the_disabled_governance_profile():
    errors = _hardened(governance_profile="disabled").production_readiness_errors()
    assert any("governance_profile" in e for e in errors)


@pytest.mark.parametrize(
    ("flag", "invariant_hint"),
    [
        ("govern_policy_enforcement", "policy broker"),
        ("govern_transactional_evidence", "atomically"),
        ("govern_tombstone_propagation", "derived memories"),
        ("admission_gate_enabled", "admissibility"),
        ("recall_gate_enabled", "audience clearance"),
        ("output_gate_enabled", "disclosure"),
    ],
)
def test_production_rejects_each_disabled_governance_control(flag, invariant_hint):
    errors = _hardened(**{flag: False}).production_readiness_errors()
    assert any(flag in e for e in errors), f"{flag}=false was accepted in production"
    assert any(invariant_hint in e for e in errors), "the error must say what breaks"


def test_production_rejects_any_ablate_environment_variable(monkeypatch):
    """Presence is disqualifying: any value flips the control off."""
    monkeypatch.setenv("MEMORYOPS_ABLATE_POLICY_BROKER", "0")
    errors = _hardened().production_readiness_errors()
    assert any("MEMORYOPS_ABLATE_POLICY_BROKER" in e for e in errors)


def test_all_governance_controls_default_to_enabled():
    """The guard must reject only deployments that explicitly turned governance off,
    never a config that simply never mentioned it."""
    s = Settings()
    assert s.governance_profile == "full"
    for flag in (
        "govern_policy_enforcement",
        "govern_transactional_evidence",
        "govern_tombstone_propagation",
        "admission_gate_enabled",
        "recall_gate_enabled",
        "output_gate_enabled",
    ):
        assert getattr(s, flag) is True, f"{flag} does not default to enabled"


def test_a_clean_production_config_is_still_accepted():
    assert _hardened().production_readiness_errors() == []


def test_app_refuses_to_import_with_governance_disabled_in_production():
    """Fail-closed startup, end to end — not merely a list of strings."""
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=_api_dir(),
        env={
            **_env(),
            "MEMORYOPS_PROFILE": "production",
            "MEMORYOPS_STORAGE": "postgres",
            "MEMORYOPS_AUTH_MODE": "trusted_header",
            "MEMORYOPS_CORS_ALLOW_ORIGINS": "https://app.example.com",
            "MEMORYOPS_DATABASE_URL": "postgresql+psycopg://real:secret@db.internal:5432/memoryops",
            "MEMORYOPS_GOVERNANCE_PROFILE": "disabled",
        },
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, "production started with governance disabled"
    assert "governance_profile" in proc.stderr


def test_research_ablation_still_works_outside_the_production_profile(monkeypatch):
    """The paper study must keep running — the guard is production-only.

    The per-control cascade lives in `get_settings()` (it resolves the env vars),
    not in the `Settings` constructor, so this exercises the real entry point.
    """
    from app.core import config

    monkeypatch.setenv("MEMORYOPS_GOVERNANCE_PROFILE", "disabled")
    config.get_settings.cache_clear()
    try:
        s = config.get_settings()
        assert s.profile == "dev"
        assert s.governance_profile == "disabled"
        # The ablation genuinely takes effect in dev...
        assert s.govern_policy_enforcement is False
        # ...and is not treated as a production violation, because it is not production.
        assert s.production_readiness_errors() == []
    finally:
        config.get_settings.cache_clear()


def test_the_env_var_cascade_is_what_production_rejects(monkeypatch):
    """The real-world shape of the hole: env vars, resolved through get_settings()."""
    from app.core import config

    for key, value in {
        "MEMORYOPS_PROFILE": "production",
        "MEMORYOPS_STORAGE": "postgres",
        "MEMORYOPS_AUTH_MODE": "jwt",
        "MEMORYOPS_CORS_ALLOW_ORIGINS": "https://app.example.com",
        "MEMORYOPS_DATABASE_URL": "postgresql+psycopg://real:secret@db.internal:5432/memoryops",
        "MEMORYOPS_PUBLIC_EVALS": "false",
        "MEMORYOPS_GOVERNANCE_PROFILE": "disabled",
    }.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    try:
        errors = config.get_settings().production_readiness_errors()
        assert errors, "a hardened production config with governance disabled was accepted"
        assert any("governance_profile" in e for e in errors)
        assert any("govern_policy_enforcement" in e for e in errors)
    finally:
        config.get_settings.cache_clear()
