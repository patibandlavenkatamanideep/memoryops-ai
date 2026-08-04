"""POST /api/chat — the write+read path entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..auth import Permission, enforce_scope, require_permission
from ..deps import gateway
from ..schemas.memory import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    enforce_scope(request, req.tenant_id, req.user_id)
    principal = require_permission(request, Permission.MEMORY_WRITE_SELF)
    if principal is not None:
        # Validating the body scope and then continuing to use it leaves untrusted
        # input in the write path: `enforce_scope` proves the values *matched* a
        # moment ago, which is not the same as them being the values we act on.
        # Everything downstream runs on the principal's scope, so a future change
        # that weakened the comparison could not become a cross-tenant write.
        req = req.model_copy(
            update={"tenant_id": principal.tenant_id, "user_id": principal.user_id}
        )
    # With auth disabled there is no principal to substitute, so the explicit request
    # scope stands — unchanged development behaviour, and safe because
    # `MEMORYOPS_PROFILE=production` refuses to start with `auth_mode=none`.
    trace_id = getattr(request.state, "trace_id", "-")
    return gateway().handle_chat(req, trace_id=trace_id)
