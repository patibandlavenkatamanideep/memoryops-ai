#!/usr/bin/env python3
"""Generate the web's authorization capability contract from the API's own objects.

Why generated
-------------
The web modelled personas as an ordinal ladder — viewer < developer < auditor <
memory_admin < owner — and asked `hasAtLeast()`. The API models capabilities, and the
two disagree in ways that matter:

  * `memory_admin` outranks `auditor` on the ladder, so it passed every auditor check.
    At the API, managing memory grants no evidence access at all.
  * `owner` outranks everything, so it passed checks for surfaces no tenant role can
    reach — deployment traces and eval execution.
  * an unrecognised path fell through to the *least* privileged role, which for a GET
    meant readable rather than denied.

A hand-maintained TypeScript mirror would drift the same way. This reads the API's
`ROUTE_AUTHZ` and `ROLE_PERMISSIONS` — the same objects the server enforces from — and
emits a committed artifact, so drift is a CI failure rather than a discovery.

Not regex over Python: the module is imported and its structured objects are walked.

The file is committed *inside* `apps/web` because the web Dockerfile builds with
`apps/web` as its context; a repo-root import is not present in that image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "apps" / "web" / "lib" / "authzCapabilities.generated.ts"
sys.path.insert(0, str(REPO / "services" / "api"))


def _ts_list(values, indent="    ") -> str:
    if not values:
        return "[]"
    inner = ", ".join(json.dumps(v) for v in sorted(values))
    return f"[{inner}]"


def render() -> str:
    from app.auth.authz_spec import ROUTE_AUTHZ, Scope, Status
    from app.auth.roles import ROLE_PERMISSIONS, Role

    contract = json.loads((REPO / "contracts" / "auth-role-map.json").read_text())

    role_perms = "\n".join(
        f"  {json.dumps(role.value)}: {_ts_list([p.value for p in perms])},"
        for role, perms in sorted(ROLE_PERMISSIONS.items(), key=lambda kv: kv[0].value)
    )

    routes = []
    for (method, template), spec in sorted(ROUTE_AUTHZ.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        entry: dict = {
            "method": method,
            "template": template,
            "scope": spec.scope.value,
            "status": spec.status.value,
        }
        if spec.permission is not None:
            entry["permission"] = spec.permission.value
        if spec.self_permission is not None:
            entry["selfPermission"] = spec.self_permission.value
        if spec.tenant_permission is not None:
            entry["tenantPermission"] = spec.tenant_permission.value
        if spec.variants:
            entry["variants"] = [
                {
                    "action": v.action,
                    **(
                        {"selfPermission": v.self_permission.value}
                        if v.self_permission is not None
                        else {}
                    ),
                    **(
                        {"tenantPermission": v.tenant_permission.value}
                        if v.tenant_permission is not None
                        else {}
                    ),
                }
                for v in spec.variants
            ]
        routes.append(entry)

    route_lines = "\n".join(f"  {json.dumps(r)}," for r in routes)
    scopes = _ts_list([s.value for s in Scope])
    statuses = _ts_list([s.value for s in Status])
    known_roles = _ts_list([r.value for r in Role])

    return f"""// GENERATED FILE — DO NOT EDIT BY HAND.
//
// Source of truth: services/api/app/auth/{{authz_spec,roles}}.py
//                  contracts/auth-role-map.json
// Regenerate:      python scripts/generate_web_capabilities.py
// Verify:          python scripts/generate_web_capabilities.py --check   (CI gate)
//
// The web used to rank personas (viewer < developer < auditor < memory_admin <
// owner) and ask "is this role at least X". The API grants capabilities, and the two
// disagree: memory_admin outranks auditor on the ladder but holds no evidence
// permission at the API, and owner outranks everything but holds no ops:* permission
// at all. This mirrors what the server actually enforces, so the disagreement cannot
// return silently.
//
// Committed inside apps/web because the web Dockerfile builds with apps/web as its
// context, so a repo-root import is not present in the image.

export const CAPABILITY_CONTRACT_VERSION = {contract.get("version", 1)};

export const API_SCOPES = {scopes} as const;
export const ROUTE_STATUSES = {statuses} as const;
export const KNOWN_API_ROLES = {known_roles} as const;

export type ApiRole = (typeof KNOWN_API_ROLES)[number];

/** Every permission each API role holds, exactly as the server computes it. */
export const ROLE_PERMISSIONS: Readonly<Record<ApiRole, readonly string[]>> = {{
{role_perms}
}} as const;

export type RouteVariant = {{
  readonly action: string;
  readonly selfPermission?: string;
  readonly tenantPermission?: string;
}};

export type RouteContract = {{
  readonly method: string;
  readonly template: string;
  readonly scope: string;
  readonly status: string;
  readonly permission?: string;
  readonly selfPermission?: string;
  readonly tenantPermission?: string;
  readonly variants?: readonly RouteVariant[];
}};

/** Every route the API classifies, with what it requires. */
export const ROUTE_CONTRACTS: readonly RouteContract[] = [
{route_lines}
] as const;
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the artifact is stale")
    args = ap.parse_args()

    rendered = render()
    if args.check:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current != rendered:
            print(
                f"✗ {TARGET.relative_to(REPO)} is stale — "
                "run python scripts/generate_web_capabilities.py",
                file=sys.stderr,
            )
            return 1
        print(f"✓ {TARGET.relative_to(REPO)} matches the API authorization contract")
        return 0

    TARGET.write_text(rendered)
    print(f"✓ wrote {TARGET.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
