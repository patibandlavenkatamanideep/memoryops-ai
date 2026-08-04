"""Runtime evidence that an authorization check actually ran.

Why a witness
-------------
The pinned ENFORCED set stops a route being *described* as enforced by accident, but
it cannot stop this sequence:

    move a route from PLANNED to ENFORCED
    update the pinned list
    forget to call the permission helper

The matrix would again claim a control that does not run — the exact failure this
whole branch exists to end. A pinned list is a claim about code; a witness is
evidence from the code.

Every authorization helper records its decision on the request. Tests for each
ENFORCED route then assert three things together: an unauthorized principal is
rejected, an authorized one succeeds, **and the expected helper actually executed
for the expected route and action**. A handler that quietly stopped checking fails
the third even when the first two still pass by coincidence.

Content-free: route, action and the permission name. Never the subject's data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Request

from .roles import Permission

#: Where the decision list lives on `request.state`.
STATE_ATTR = "memoryops_authz"


@dataclass(frozen=True)
class AuthzDecision:
    """One authorization check that ran."""

    route: tuple[str, str]
    #: Which helper produced it — permission / subject / resource / transition.
    helper: str
    permission: Permission | None = None
    #: For multi-action routes (PATCH), the validated action that was authorized.
    action: str | None = None
    #: True when the caller was authorized via a tenant-wide permission rather than
    #: a self permission. Useful for asserting the *right* branch was taken.
    tenant_scoped: bool = False
    detail: str = ""


@dataclass
class AuthzWitness:
    decisions: list[AuthzDecision] = field(default_factory=list)

    def record(self, decision: AuthzDecision) -> None:
        self.decisions.append(decision)

    @property
    def routes(self) -> tuple[tuple[str, str], ...]:
        return tuple(d.route for d in self.decisions)

    def for_route(self, method: str, path: str) -> tuple[AuthzDecision, ...]:
        return tuple(d for d in self.decisions if d.route == (method, path))

    def __bool__(self) -> bool:
        return bool(self.decisions)


def record_decision(request: Request | None, decision: AuthzDecision) -> None:
    """Attach a decision to the request, if there is one.

    No-throw and no-op without a request: authorization must not fail because its
    own bookkeeping did.
    """
    if request is None:
        return
    state = getattr(request, "state", None)
    if state is None:
        return
    witness = getattr(state, STATE_ATTR, None)
    if witness is None:
        witness = AuthzWitness()
        setattr(state, STATE_ATTR, witness)
    witness.record(decision)


def witness_for(request: Request) -> AuthzWitness:
    """The decisions recorded on this request; empty when nothing checked."""
    return getattr(getattr(request, "state", None), STATE_ATTR, None) or AuthzWitness()


def route_of(request: Request) -> tuple[str, str] | None:
    """The (METHOD, path-template) FastAPI matched, for recording."""
    route = getattr(getattr(request, "scope", {}), "get", lambda _k: None)("route")
    if route is None and isinstance(getattr(request, "scope", None), dict):
        route = request.scope.get("route")
    path = getattr(route, "path", None)
    if not path:
        return None
    return (request.method, path)
