"""Error taxonomy + one shared retry policy for the extraction harness (§11).

Only genuine transport failures are retryable. Invalid/unusable *content* (bad JSON,
schema mismatch, refusal, truncation, empty) is recorded as an outcome and **never**
silently regenerated — regenerating on a content failure would bias reliability metrics.
No provider ever falls back to another provider.
"""

from __future__ import annotations

from enum import Enum


class ErrorClass(str, Enum):
    rate_limit_error = "rate_limit_error"
    provider_error = "provider_error"  # 5xx / server-side
    network_error = "network_error"  # timeout / connection
    structured_output_error = "structured_output_error"  # provider couldn't do structured out
    schema_validation_error = "schema_validation_error"  # parsed but failed our schema
    refusal = "refusal"
    truncation = "truncation"
    empty_response = "empty_response"
    unknown_error = "unknown_error"


# Transport failures we retry (with backoff+jitter). Everything else is terminal.
RETRYABLE: frozenset[ErrorClass] = frozenset(
    {ErrorClass.rate_limit_error, ErrorClass.provider_error, ErrorClass.network_error}
)


def is_retryable(error_class: ErrorClass | str | None) -> bool:
    if error_class is None:
        return False
    if isinstance(error_class, str):
        try:
            error_class = ErrorClass(error_class)
        except ValueError:
            return False
    return error_class in RETRYABLE
