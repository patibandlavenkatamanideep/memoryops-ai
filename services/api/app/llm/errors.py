"""Retry classification for networked LLM providers.

Retry only failures that could plausibly succeed on a **subsequent identical
request**. Everything else fails fast.

Why this exists
---------------
The shared retry envelope in ``core.reliability.with_retry`` originally retried on
*any* exception. A deterministic ``400 INVALID_ARGUMENT`` is not a transient fault —
the identical request will be rejected identically — so retrying it only multiplies
load and latency before the same failure. That is not hypothetical: a Gemini
evidence run whose deadline was below the API's 10-second floor turned 25 logical
calls into 75 HTTP requests, three rejections per call, before degrading to the
heuristic. The wasted attempts changed nothing except how long the failure took.

Classification rules (derived from the SDKs, not assumed)
---------------------------------------------------------
1. **An HTTP status, when present, is authoritative.** Retryable statuses are
   ``408`` (request timeout), ``409`` (lock timeout), ``429`` (rate limit) and any
   ``5xx``. This set is not invented here: it is exactly what the OpenAI and
   Anthropic SDKs implement in their own ``_base_client._should_retry`` — including
   the two that look permanent at a glance. 408 and 409 are documented *in those
   SDKs* as request timeout and lock timeout respectively, both of which do resolve
   on an identical retry. ``google-genai`` uses a narrower list
   (``429/500/502/503/504``), which is a subset, so the union stays consistent with
   all three.
2. **Otherwise, transport failures are retryable** — connection and timeout errors,
   which carry no status because no response was received.
3. **Otherwise, fail fast.** An unrecognised exception is treated as permanent.

Rule 3 is the deliberate part. Defaulting the unknown case to "retry" is precisely
what produced the original defect: a local ``TypeError`` or a malformed request is
deterministic, and retrying it three times only delays the fallback. Fail-fast on
unknown loses nothing that matters — the caller degrades to the deterministic
heuristic either way (invariant #4) — while retry-on-unknown costs real time on
every programming or configuration error.

No SDK imports
--------------
Provider SDKs are optional extras; the API package must import and its suite must
collect with none of them installed. So classification is duck-typed over attributes
the SDKs actually expose (verified against the pinned versions) rather than by
``isinstance`` against imported types:

===============  =========================  ==============================
SDK              status attribute           transport errors
===============  =========================  ==============================
``openai``       ``.status_code`` (int)     ``APIConnectionError`` /
                                            ``APITimeoutError``
``anthropic``    ``.status_code`` (int)     ``APIConnectionError`` /
                                            ``APITimeoutError``
``google-genai`` ``.code`` (int)            raw ``httpx.ConnectError`` /
                                            ``httpx.TimeoutException``
===============  =========================  ==============================

``google-genai`` raises no per-status exception subclasses — a 400 and a 429 are
both ``ClientError`` — so classifying Gemini by exception *type* is not possible.
Reading the numeric code is what makes Gemini's rate limit retryable and its
invalid-argument permanent.
"""

from __future__ import annotations

#: Statuses worth a second identical attempt. Mirrors OpenAI's and Anthropic's own
#: ``_should_retry``; 5xx is handled separately as a range.
RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 409, 429})

#: Substrings that identify a transport failure by class name, used only when no
#: HTTP status is available. Matched against the exception's whole MRO so SDK
#: wrappers (``openai.APITimeoutError``) and the raw httpx errors that
#: ``google-genai`` propagates (``ConnectTimeout``, ``ReadTimeout``,
#: ``ConnectError``) are both recognised, as are the builtins ``TimeoutError`` and
#: ``ConnectionResetError``.
_TRANSPORT_MARKERS: tuple[str, ...] = ("timeout", "connect", "retryable")


def status_code_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status for a provider exception, or ``None``.

    ``status_code`` (OpenAI/Anthropic) is preferred over ``code`` (google-genai)
    because OpenAI's ``APIError`` also carries a ``code`` attribute holding a
    *string* error slug. The ``int`` check keeps that slug from being mistaken for
    a status; the range check keeps unrelated ``code`` attributes (``SystemExit``)
    out.
    """
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        # bool is an int subclass; a True here would otherwise read as status 1.
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return None


def _looks_like_transport_failure(exc: BaseException) -> bool:
    names = " ".join(cls.__name__.lower() for cls in type(exc).__mro__)
    return any(marker in names for marker in _TRANSPORT_MARKERS)


def is_retryable_provider_error(exc: BaseException) -> bool:
    """Whether an identical retry of the failed provider call could succeed.

    Fails fast on anything unrecognised — see the module docstring for why the
    unknown case must not default to retrying.
    """
    status = status_code_of(exc)
    if status is not None:
        # Authoritative: a 400 stays permanent even if the class name happens to
        # contain a transport-ish word.
        return status in RETRYABLE_STATUS_CODES or status >= 500
    return _looks_like_transport_failure(exc)
