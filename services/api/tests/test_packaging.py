"""Packaging guards: the wheel must carry everything the app reads at runtime.

Two failure modes this locks down, both of which shipped silently because a source
checkout masks them (the files are simply there on disk):

1. **Missing package data.** `app/llm/prompt_registry.py` resolves its system
   prompts as `Path(__file__).parent / "prompts" / "<task>.md"` and reads them at
   call time. The wheel declared no `package-data`, so those Markdown files were
   omitted and every structured-intelligence call — extraction, conflict detection,
   merge recommendation — raised `PromptNotFoundError` in a wheel-installed
   deployment while passing in CI and in dev.

2. **Dependency drift.** `pyproject.toml` is the source of truth; every
   `requirements*.txt` is generated from it by `scripts/sync_dependencies.py`.
   They had diverged (fastapi 0.139.2 vs 0.140.0, uvicorn 0.37.0 vs 0.51.0,
   pydantic-settings 2.6.1 vs 2.14.2), so the image and the wheel resolved
   different dependency sets.

The full build-install-boot proof runs in the `packaging` CI job; these tests are
the fast local guard.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]
PYPROJECT = API_DIR / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


# ── package data ─────────────────────────────────────────────────────────────
def _runtime_asset_dirs() -> set[Path]:
    """Directories under app/ holding non-Python files the app reads at runtime."""
    found: set[Path] = set()
    for path in (API_DIR / "app").rglob("*"):
        if not path.is_file() or path.suffix == ".py":
            continue
        if "__pycache__" in path.parts:
            continue
        found.add(path.parent)
    return found


def test_every_runtime_asset_dir_is_declared_as_package_data(pyproject):
    """A new non-.py asset under app/ must be added to [tool.setuptools.package-data].

    Otherwise it works in dev and vanishes from the wheel.
    """
    declared = pyproject["tool"]["setuptools"]["package-data"]
    # Expand "app.llm": ["prompts/*.md"] into the directories it covers.
    covered: set[Path] = set()
    for package, patterns in declared.items():
        pkg_dir = API_DIR / Path(package.replace(".", "/"))
        for pattern in patterns:
            for match in pkg_dir.glob(pattern):
                covered.add(match.parent)

    undeclared = sorted(
        str(d.relative_to(API_DIR)) for d in _runtime_asset_dirs() - covered
    )
    assert not undeclared, (
        "runtime assets under app/ are not declared as setuptools package-data and "
        f"would be missing from the wheel: {undeclared}"
    )


def test_prompt_assets_are_covered_by_package_data(pyproject):
    """Explicit regression guard for the prompt files specifically."""
    patterns = pyproject["tool"]["setuptools"]["package-data"].get("app.llm", [])
    matched = {p.name for pattern in patterns for p in (API_DIR / "app/llm").glob(pattern)}
    on_disk = {p.name for p in (API_DIR / "app/llm/prompts").glob("*.md")}
    assert on_disk, "no prompt files on disk — did the registry layout change?"
    assert on_disk <= matched, f"prompts missing from package-data: {sorted(on_disk - matched)}"


def test_all_registered_prompts_exist_on_disk():
    """The registry's task table must not reference a file that isn't shipped."""
    from app.llm.prompt_registry import available_tasks, get_prompt

    for task in available_tasks():
        assert get_prompt(task).strip(), f"empty or missing prompt asset: {task}"


def test_tests_are_not_packaged(pyproject):
    include = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    assert include == ["app*"], "packages.find must stay explicit so tests aren't shipped"


# ── dependency source of truth ───────────────────────────────────────────────
def test_requirements_files_match_pyproject():
    """`requirements*.txt` are generated; drift means the image and wheel differ."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "sync_dependencies.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"dependency drift between pyproject.toml and requirements*.txt:\n"
        f"{proc.stdout}\n{proc.stderr}\n"
        "Run: python scripts/sync_dependencies.py"
    )


def test_provider_extras_pin_the_module_each_adapter_imports(pyproject):
    """An extra must install the SDK its adapter actually imports.

    `app/llm/gemini_provider.py` imports `google.generativeai` (the legacy
    `google-generativeai` distribution), not `google.genai` (`google-genai`).
    Pinning the wrong one installs an SDK the adapter cannot use — a broken extra
    that looks correct.
    """
    extras = pyproject["project"]["optional-dependencies"]
    expected_distribution = {
        "openai": "openai",
        "anthropic": "anthropic",
        "gemini": "google-generativeai",
        "qdrant": "qdrant-client",
        "lancedb": "lancedb",
        "weaviate": "weaviate-client",
    }
    for extra, distribution in expected_distribution.items():
        pins = extras[extra]
        assert any(p.split("==")[0] == distribution for p in pins), (
            f"extra '{extra}' must pin '{distribution}', got {pins}"
        )
        assert all("==" in p for p in pins), f"extra '{extra}' must use exact pins: {pins}"


def test_production_extra_covers_postgres_and_all_providers(pyproject):
    """The production images install this; it must be able to honour any
    MEMORYOPS_LLM_PROVIDER / MEMORYOPS_STORAGE=postgres selection."""
    pins = pyproject["project"]["optional-dependencies"]["production"]
    production = {p.split("==")[0] for p in pins}
    for required in (
        "sqlalchemy",
        "psycopg",
        "pgvector",
        "openai",
        "anthropic",
        "google-generativeai",
    ):
        assert any(name.startswith(required) for name in production), (
            f"production extra is missing {required}: {sorted(production)}"
        )
