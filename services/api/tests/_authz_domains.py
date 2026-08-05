"""Which enforced routes are covered by a *runtime* witness gate, and by which one.

Shared so the coverage guard and the gates themselves cannot disagree. A route in one
of these domains must be driven through the real app by that domain's gate; a route in
none of them has to be named explicitly in the coverage guard, which is the case that
would otherwise slip through unnoticed.

The predicates take the **method** as well as the path: `/api/retention/*` holds both
reads and mutations, and they are gated by different files, so a path-only predicate
would make the read gate responsible for the mutations it does not drive.
"""

from __future__ import annotations

_GOVERNANCE_PREFIXES = ("/api/evidence", "/api/retention", "/api/loops")
_GOVERNANCE_PATHS = frozenset({"/api/traces", "/api/evals/latest"})


def is_memory_domain(method: str, path: str) -> bool:
    return path.startswith("/api/memories") or path == "/api/chat"


def is_governance_read(method: str, path: str) -> bool:
    if method != "GET":
        return False
    return path.startswith(_GOVERNANCE_PREFIXES) or path in _GOVERNANCE_PATHS


def is_governance_mutation(method: str, path: str) -> bool:
    return method == "POST" and path.startswith("/api/retention/")


def is_runtime_gated(method: str, path: str) -> bool:
    return (
        is_memory_domain(method, path)
        or is_governance_read(method, path)
        or is_governance_mutation(method, path)
    )


def enforced_in(route_authz, status_enforced, predicate) -> set[tuple[str, str]]:
    return {
        (m, p)
        for (m, p), spec in route_authz.items()
        if spec.status is status_enforced and predicate(m, p)
    }
