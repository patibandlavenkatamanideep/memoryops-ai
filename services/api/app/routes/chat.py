"""POST /api/chat — the write+read path entrypoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ..auth import enforce_scope
from ..deps import gateway
from ..schemas.memory import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> ChatResponse:
    enforce_scope(request, req.tenant_id, req.user_id)
    trace_id = getattr(request.state, "trace_id", "-")
    return gateway().handle_chat(req, trace_id=trace_id)
