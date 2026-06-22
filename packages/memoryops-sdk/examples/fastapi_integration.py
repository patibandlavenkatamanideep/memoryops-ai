"""FastAPI integration: put governed memory behind your own assistant endpoint.

Your app stays in control of the HTTP surface; MemoryOps handles capture, policy,
retrieval, and audit. The per-user scope comes from your auth layer (here a
header, for brevity) and is passed straight to the SDK.

Run:

    pip install fastapi uvicorn memoryops-sdk
    uvicorn examples.fastapi_integration:app --reload
    curl -s localhost:8000/assistant -H 'x-user-id: user_demo' \
         -H 'content-type: application/json' -d '{"message":"Remember I like tea."}'
"""

from __future__ import annotations

from fastapi import FastAPI, Header
from pydantic import BaseModel

from memoryops import MemoryOpsClient

MEMORYOPS_URL = "http://localhost:8000"  # the MemoryOps API (not this app)
TENANT_ID = "tenant_demo"

app = FastAPI(title="My Assistant (MemoryOps-backed)")


class AskRequest(BaseModel):
    message: str


def _client(user_id: str) -> MemoryOpsClient:
    # One client per request scope; cheap to construct. In production share a
    # single httpx.Client via the http_client= argument for connection pooling.
    return MemoryOpsClient(MEMORYOPS_URL, tenant_id=TENANT_ID, user_id=user_id)


@app.post("/assistant")
def assistant(req: AskRequest, x_user_id: str = Header(...)) -> dict:
    with _client(x_user_id) as mo:
        result = mo.chat(req.message)
        return {
            "reply": result.assistant_message,
            "used_memories": [u.content for u in result.used_memories],
            "trace_id": result.trace_id,
        }


@app.get("/assistant/memories")
def list_memories(x_user_id: str = Header(...)) -> list[dict]:
    with _client(x_user_id) as mo:
        return [{"id": m.id, "type": m.memory_type, "content": m.content}
                for m in mo.list_memories()]
