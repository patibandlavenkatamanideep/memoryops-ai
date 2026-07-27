"""Provider contract for the extraction harness.

Every provider separates two responsibilities so the parsing/normalisation path is
fully testable offline against recorded fixtures, with the live network call isolated:

* ``parse(raw_text)`` — deterministic: turn a provider's raw text into a validated
  ``ExtractionOutput`` **or** an ``ErrorClass`` (invalid JSON / schema / empty). No
  network, no keys — this is what the contract tests exercise on recorded fixtures.
* ``extract(...)`` — live: build the provider-specific structured-output request from
  the shared logical prompt, call the SDK, capture usage/model-id/response-id, then
  ``parse`` the raw text. Only reachable under an explicit ``--live`` flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from ..errors import ErrorClass
from ..schema import ExtractionOutput


@dataclass
class ProviderResult:
    """Outcome of a single provider call (one case, one repetition)."""

    output: ExtractionOutput | None = None
    raw_text: str = ""
    error_class: str | None = None  # ErrorClass value, or None on success
    error_detail: str = ""
    retry_count: int = 0
    error_history: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int | None = None
    api_model_id: str = ""
    response_id: str = ""
    sdk_version: str = ""
    finish_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.output is not None and self.error_class is None


class Provider(Protocol):
    name: str  # "stub" | "gemini" | "openai" | "anthropic"
    configured_model_id: str

    def available(self) -> bool:
        """True iff this provider can run live here (SDK importable + key present)."""
        ...

    def is_live(self) -> bool:
        """False for the deterministic stub, True for network providers."""
        ...

    def parse(self, raw_text: str) -> tuple[ExtractionOutput | None, ErrorClass | None, str]:
        """Deterministic normalisation → (output, error_class, detail)."""
        ...

    def extract(self, *, prompt: str, conversation: list[dict], target_turn_id: str) -> ProviderResult:
        """Live call (requires --live). Never falls back to another provider."""
        ...


def parse_json_output(raw_text: str) -> tuple[ExtractionOutput | None, ErrorClass | None, str]:
    """Shared deterministic parser: JSON object with a ``memories`` list → validated
    ``ExtractionOutput``. Classifies empty / invalid-JSON / schema failures. Used by the
    network adapters after they extract the raw text from their SDK response."""
    text = (raw_text or "").strip()
    if not text:
        return None, ErrorClass.empty_response, "empty response"
    # Tolerate a fenced ```json block; do not tolerate anything else (strictness is the
    # point — a provider that can't emit clean structured output is a reliability signal).
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:].strip() if text.lower().startswith("json") else text.strip()
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, ErrorClass.structured_output_error, f"invalid JSON: {type(exc).__name__}"
    if not isinstance(payload, dict) or "memories" not in payload:
        return None, ErrorClass.schema_validation_error, "missing 'memories' key"
    try:
        return ExtractionOutput.model_validate(payload), None, ""
    except Exception as exc:  # noqa: BLE001 — any validation failure is a schema error outcome
        return None, ErrorClass.schema_validation_error, str(exc)[:200]
