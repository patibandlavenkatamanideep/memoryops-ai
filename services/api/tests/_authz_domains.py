"""Which enforced routes are covered by a *runtime* witness gate, and by which one.

Shared so the coverage guard and the gates themselves cannot disagree. A route in one
of these domains must be driven through the real app by that domain's gate; a route in
none of them has to be named explicitly in the coverage guard, which is the case that
would otherwise slip through unnoticed.
"""

from __future__ import annotations


def is_memory_domain(path: str) -> bool:
    return path.startswith("/api/memories") or path == "/api/chat"


def is_governance_domain(path: str) -> bool:
    return path.startswith(("/api/evidence", "/api/retention", "/api/loops")) or path in {
        "/api/traces",
        "/api/evals/latest",
    }


def enforced_in(route_authz, status_enforced, predicate) -> set[tuple[str, str]]:
    return {
        (m, p)
        for (m, p), spec in route_authz.items()
        if spec.status is status_enforced and predicate(p)
    }
