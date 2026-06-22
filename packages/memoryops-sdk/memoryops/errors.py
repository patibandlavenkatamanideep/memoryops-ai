"""Typed errors raised by the MemoryOps SDK."""

from __future__ import annotations


class MemoryOpsError(Exception):
    """Base class for all SDK errors."""


class APIError(MemoryOpsError):
    """A non-2xx HTTP response from the MemoryOps API.

    Carries the status code, the parsed ``detail`` (when present), and the raw
    response body so callers can branch on either.
    """

    def __init__(self, status_code: int, detail: str | None = None, body: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        self.body = body
        super().__init__(f"HTTP {status_code}: {detail or body or 'request failed'}")


class NotFoundError(APIError):
    """A 404 — the memory (or other resource) does not exist in this scope."""


class LegalHoldError(APIError):
    """A 409 from a delete blocked by an active legal hold (v0.10).

    Release the hold with :meth:`MemoryOpsClient.set_legal_hold` (``on=False``)
    before deleting.
    """
