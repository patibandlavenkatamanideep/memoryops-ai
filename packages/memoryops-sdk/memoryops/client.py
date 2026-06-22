"""MemoryOpsClient — a small, typed Python client for the MemoryOps AI API.

It wraps the HTTP surface (chat, memories, retention/legal-hold/consent, audit,
metrics, loops, health) and injects the ``tenant_id`` / ``user_id`` scope on every
call so application code never hand-builds request bodies. Tenant isolation,
the deletion guarantee, policy-before-storage, and auditability are enforced by
the server — the SDK is a thin, faithful client over that governed API.

Example::

    from memoryops import MemoryOpsClient

    with MemoryOpsClient("http://localhost:8000", "tenant_demo", "user_demo") as mo:
        result = mo.chat("Remember I prefer metric units.")
        print(result.assistant_message)
        for m in mo.list_memories():
            print(m.memory_type, m.content)

The client is synchronous and built on ``httpx``. For tests or in-process use you
can pass a pre-built ``httpx.Client`` (e.g. one bound to an ASGI app) via
``http_client``.
"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import APIError, LegalHoldError, NotFoundError
from .models import AuditEvent, ChatResult, Memory, RetentionDecision

__all__ = ["MemoryOpsClient"]


class MemoryOpsClient:
    def __init__(
        self,
        base_url: str,
        tenant_id: str,
        user_id: str,
        *,
        timeout: float = 30.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> MemoryOpsClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ── transport ──────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._http.request(method, path, **kwargs)
        if resp.status_code >= 400:
            self._raise(resp)
        if resp.content:
            return resp.json()
        return None

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        detail: str | None = None
        try:
            detail = resp.json().get("detail")
        except Exception:  # noqa: BLE001 — non-JSON error bodies are fine
            detail = None
        if resp.status_code == 404:
            raise NotFoundError(resp.status_code, detail, resp.text)
        if resp.status_code == 409:
            raise LegalHoldError(resp.status_code, detail, resp.text)
        raise APIError(resp.status_code, detail, resp.text)

    def _scope(self, **extra: Any) -> dict:
        return {"tenant_id": self.tenant_id, "user_id": self.user_id, **extra}

    # ── chat ───────────────────────────────────────────────────────────────────
    def chat(
        self,
        message: str,
        *,
        temporary_chat: bool = False,
        conversation_id: str | None = None,
    ) -> ChatResult:
        """Send a message through the governed memory pipeline (write + read).

        With ``temporary_chat=True`` the server reads and writes nothing
        (invariant #6) — useful for one-off prompts that must not be remembered.
        """
        body = self._scope(
            message=message,
            temporary_chat=temporary_chat,
            conversation_id=conversation_id,
        )
        return ChatResult.from_dict(self._request("POST", "/api/chat", json=body))

    # ── memories ───────────────────────────────────────────────────────────────
    def list_memories(
        self, *, status: str | None = None, memory_type: str | None = None
    ) -> list[Memory]:
        params = self._scope()
        if status:
            params["status"] = status
        if memory_type:
            params["memory_type"] = memory_type
        rows = self._request("GET", "/api/memories", params=params)
        return [Memory.from_dict(r) for r in rows]

    def get_memory(self, memory_id: str) -> Memory:
        return Memory.from_dict(
            self._request("GET", f"/api/memories/{memory_id}", params=self._scope())
        )

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: int | None = None,
        confidence: float | None = None,
        status: str | None = None,
    ) -> Memory:
        body = self._scope()
        for key, val in (
            ("content", content),
            ("importance", importance),
            ("confidence", confidence),
            ("status", status),
        ):
            if val is not None:
                body[key] = val
        return Memory.from_dict(self._request("PATCH", f"/api/memories/{memory_id}", json=body))

    def delete_memory(self, memory_id: str) -> dict:
        """Soft-delete a memory.

        Raises :class:`LegalHoldError` (HTTP 409) if the memory is under legal
        hold — release the hold first (``set_legal_hold(..., on=False)``).
        """
        return self._request("DELETE", f"/api/memories/{memory_id}", json=self._scope())

    def memory_audit(self, memory_id: str, *, limit: int = 200) -> list[AuditEvent]:
        rows = self._request(
            "GET", f"/api/memories/{memory_id}/audit", params=self._scope(limit=limit)
        )
        return [AuditEvent.from_dict(r) for r in rows]

    def memory_provenance(self, memory_id: str) -> dict:
        return self._request("GET", f"/api/memories/{memory_id}/provenance", params=self._scope())

    # ── retention / legal hold / consent (v0.10) ───────────────────────────────
    def set_legal_hold(self, memory_id: str, *, on: bool, reason: str | None = None) -> dict:
        body = self._scope(memory_id=memory_id, on=on, reason=reason)
        return self._request("POST", "/api/retention/legal-hold", json=body)

    def pin(self, memory_id: str, *, on: bool = True) -> dict:
        return self._request(
            "POST", "/api/retention/pin", json=self._scope(memory_id=memory_id, on=on)
        )

    def protect(self, memory_id: str, *, on: bool = True) -> dict:
        return self._request(
            "POST", "/api/retention/protect", json=self._scope(memory_id=memory_id, on=on)
        )

    def set_consent(
        self, memory_id: str, *, status: str, expires_at: str | None = None
    ) -> dict:
        body = self._scope(memory_id=memory_id, status=status, expires_at=expires_at)
        return self._request("POST", "/api/retention/consent", json=body)

    def retention_policies(self) -> list[dict]:
        return self._request("GET", "/api/retention/policies")["policies"]

    def retention_decisions(self, *, policy: str | None = None) -> list[RetentionDecision]:
        """Read-only preview of retention decisions for active memory in scope.

        Deletes nothing — this is exactly what the retention worker would act on
        when enabled.
        """
        params = self._scope()
        if policy:
            params["policy"] = policy
        body = self._request("GET", "/api/retention/decisions", params=params)
        return [RetentionDecision.from_dict(d) for d in body["decisions"]]

    def memory_governance(self, memory_id: str, *, policy: str | None = None) -> dict:
        params = self._scope()
        if policy:
            params["policy"] = policy
        return self._request("GET", f"/api/retention/memory/{memory_id}", params=params)

    # ── audit / metrics / loops / health ───────────────────────────────────────
    def audit(self, *, memory_id: str | None = None, limit: int = 200) -> list[AuditEvent]:
        params = self._scope(limit=limit)
        if memory_id:
            params["memory_id"] = memory_id
        rows = self._request("GET", "/api/audit", params=params)
        return [AuditEvent.from_dict(r) for r in rows]

    def metrics(self) -> dict:
        return self._request("GET", "/api/metrics", params={"tenant_id": self.tenant_id})

    def loops(self) -> list[dict]:
        return self._request("GET", "/api/loops")

    def loop_trace(self, trace_id: str) -> dict:
        return self._request("GET", f"/api/loops/trace/{trace_id}")

    def health(self) -> dict:
        return self._request("GET", "/healthz")

    def workers_health(self) -> dict:
        return self._request("GET", "/healthz/workers")
