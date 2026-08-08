#!/usr/bin/env python3
"""Generate apps/web/lib/roleMap.generated.ts from contracts/auth-role-map.json.

Why generate instead of importing the JSON directly
---------------------------------------------------
`contracts/auth-role-map.json` is the single source of truth for the web-persona →
API-role translation, and it lives at the repository root so both sides can read it.
The API reads it in tests, which run from a checkout — fine.

The web app needs it at *build* time, and `apps/web/Dockerfile` builds with
`apps/web` as its context, so a `../../../contracts/...` import is simply not
present in the image. The production build failed exactly there.

Rather than widen the Docker context to the whole repository, this mirrors the
pattern already proven for dependencies (`scripts/sync_dependencies.py`): the
contract stays authoritative, a generated file is committed inside the build
context, and CI fails on drift so the two cannot diverge.

Usage:
    python scripts/sync_role_contract.py            # regenerate
    python scripts/sync_role_contract.py --check    # exit 1 on drift (CI gate)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "contracts" / "auth-role-map.json"
GENERATED = REPO_ROOT / "apps" / "web" / "lib" / "roleMap.generated.ts"


def render(contract: dict) -> str:
    web_to_api = contract["web_to_api"]
    api_roles = contract["api_roles"]
    never_human = contract.get("never_assignable_to_humans", [])
    never_web = contract.get("never_web_assignable", {}).get("roles", [])

    entries = "\n".join(f'  {k}: "{v}",' for k, v in web_to_api.items())
    roles = "\n".join(f'  "{r}",' for r in api_roles)
    machine = "\n".join(f'  "{r}",' for r in never_human)
    web_forbidden = "\n".join(f'  "{r}",' for r in never_web)

    return f"""// GENERATED FILE — DO NOT EDIT BY HAND.
//
// Source of truth: contracts/auth-role-map.json
// Regenerate:      python scripts/sync_role_contract.py
// Verify:          python scripts/sync_role_contract.py --check   (CI gate)
//
// Committed inside apps/web because the web Dockerfile builds with apps/web as its
// context, so a repo-root import is not present in the image.

export const WEB_TO_API_ROLE_MAP = {{
{entries}
}} as const;

export const API_ROLES = [
{roles}
] as const;

export const NEVER_ASSIGNABLE_TO_HUMANS = [
{machine}
] as const;

// Roles the BFF must never mint from a UI persona. Broader than the list above:
// `platform_operator` *is* assignable to a person, but never as a tenant's web
// session — no customer's UI may become deployment authority.
export const NEVER_WEB_ASSIGNABLE = [
{web_forbidden}
] as const;

export const ROLE_CONTRACT_VERSION = {contract.get("version", 1)};
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on drift")
    args = parser.parse_args()

    expected = render(json.loads(CONTRACT.read_text()))
    current = GENERATED.read_text() if GENERATED.exists() else None

    if current == expected:
        print("✓ apps/web/lib/roleMap.generated.ts matches contracts/auth-role-map.json")
        return 0

    if args.check:
        print(
            "Role contract drift: apps/web/lib/roleMap.generated.ts no longer matches\n"
            "contracts/auth-role-map.json, which is the source of truth.\n\n"
            "    python scripts/sync_role_contract.py\n\n"
            "then commit the regenerated file.",
            file=sys.stderr,
        )
        return 1

    GENERATED.write_text(expected)
    print(f"✓ wrote {GENERATED.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
