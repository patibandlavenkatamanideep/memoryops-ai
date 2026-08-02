#!/usr/bin/env python3
"""Generate (and drift-check) services/api/requirements*.txt from pyproject.toml.

Why this exists
---------------
The API had two independent dependency sources that had silently diverged:
``pyproject.toml`` pinned fastapi 0.139.2 / uvicorn 0.37.0 / pydantic-settings 2.6.1
while ``requirements.txt`` pinned 0.140.0 / 0.51.0 / 2.14.2. Docker and CI install
the requirements files; ``pip install .`` and the published wheel resolve the
pyproject set. A green CI run therefore proved nothing about the package metadata,
and nothing about the image if the two drifted again.

``pyproject.toml`` is now authoritative. This script materialises every
requirements file listed under ``[tool.memoryops.requirements]`` from it.

Usage
-----
    python scripts/sync_dependencies.py            # rewrite the generated files
    python scripts/sync_dependencies.py --check    # exit 1 on drift (CI gate)

Deliberately dependency-free: stdlib ``tomllib`` only, so it runs in any clean
environment (including the CI job that runs before deps are installed).
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
PYPROJECT = API_DIR / "pyproject.toml"

BANNER = (
    "# ─────────────────────────────────────────────────────────────────────────\n"
    "# GENERATED FILE — DO NOT EDIT BY HAND.\n"
    "#\n"
    "# Source of truth: services/api/pyproject.toml\n"
    "# Regenerate:      python scripts/sync_dependencies.py\n"
    "# Verify:          python scripts/sync_dependencies.py --check   (CI gate)\n"
    "#\n"
    "# Hand-edits are reverted by the next regeneration and fail the CI drift gate.\n"
    "# ─────────────────────────────────────────────────────────────────────────\n"
)


def load_pyproject() -> dict:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def render(name: str, spec: dict, project: dict) -> str:
    """Render one requirements file from its spec."""
    base_deps: list[str] = project.get("dependencies", [])
    extras_table: dict[str, list[str]] = project.get("optional-dependencies", {})

    lines = [BANNER]

    for required in spec.get("requires", []):
        lines.append(f"-r {required}\n")
    if spec.get("requires"):
        lines.append("\n")

    if spec.get("include_base", False):
        lines.append("# [project].dependencies\n")
        lines.extend(f"{dep}\n" for dep in base_deps)
        lines.append("\n")

    for extra in spec.get("extras", []):
        if extra not in extras_table:
            raise SystemExit(
                f"{name}: unknown extra {extra!r}. "
                f"Known extras: {', '.join(sorted(extras_table)) or '(none)'}"
            )
        lines.append(f"# [project.optional-dependencies].{extra}\n")
        lines.extend(f"{dep}\n" for dep in extras_table[extra])
        lines.append("\n")

    # Collapse the trailing blank line so the file ends with exactly one newline.
    text = "".join(lines)
    return text.rstrip("\n") + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the generated files match pyproject.toml; exit 1 on drift",
    )
    args = parser.parse_args()

    data = load_pyproject()
    project = data["project"]
    targets = data.get("tool", {}).get("memoryops", {}).get("requirements", {})
    if not targets:
        raise SystemExit(
            "no [tool.memoryops.requirements] entries in pyproject.toml — nothing to generate"
        )

    drifted: list[str] = []
    written: list[str] = []

    for name, spec in targets.items():
        path = API_DIR / name
        expected = render(name, spec, project)
        current = path.read_text() if path.exists() else None

        if current == expected:
            continue

        if args.check:
            drifted.append(name)
            if current is None:
                print(f"  ✗ {name}: missing (would be generated)")
            else:
                print(f"  ✗ {name}: differs from pyproject.toml")
        else:
            path.write_text(expected)
            written.append(name)
            print(f"  ✓ wrote services/api/{name}")

    if args.check:
        if drifted:
            print(
                "\nDependency drift detected: the generated requirements files no longer\n"
                "match services/api/pyproject.toml. pyproject.toml is the source of truth.\n"
                "\n    python scripts/sync_dependencies.py\n\n"
                "then commit the regenerated files.",
                file=sys.stderr,
            )
            return 1
        print(f"✓ all {len(targets)} requirements files match pyproject.toml")
        return 0

    if not written:
        print(f"✓ all {len(targets)} requirements files already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
