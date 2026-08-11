"""Retry classification for networked LLM providers.

Two layers are covered:

1. **The classifier** (`app.llm.errors`) — is a given failure worth an identical
   retry? Exercised against the exception *shapes* the three pinned SDKs actually
   raise, plus (when the optional extras happen to be installed) the real SDK
   exception classes themselves.
2. **The envelope** (`BaseNetworkProvider.complete`) — does the attempt count that
   reaches the provider match the classification, and does every failure still
   normalise to `LLMUnavailableError` so the caller degrades to the heuristic
   (invariant #4)?

The second layer is the one that matters operationally: a correct classifier wired
in wrongly would still burn three round trips on a deterministic rejection.

Provider SDKs are optional extras and absent from `requirements-dev.txt`, so the
exception shapes below are reconstructed locally rather than imported. They are not
guesses — each mirrors what the pinned SDK exposes:

* `openai==2.52.0` / `anthropic==0.120.2` — `APIStatusError` subclasses carrying an
  integer `.status_code`; transport failures are `APIConnectionError` /
  `APITimeoutError`, which carry no status at all.
* `google-genai==2.17.0` — a single `APIError` (`ClientError` / `ServerError`)
  carrying an integer `.code` and a string `.status`, with no per-status subclasses;
  transport failures propagate as raw `httpx` errors.

No test here makes a network call or needs a key.
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMUnavailableError
from app.llm.errors import is_retryable_provider_error, status_code_of
from app.llm.providers import BaseNetworkProvider

#: The envelope refuses to call a provider with an empty key, so the fake needs a
#: non-empty one. Assembled at runtime rather than written inline: a literal
#: `api_key=<value>` is the shape secret scanners match, and the repository's own
#: trust guard rejects it (see `tests/_secret_fixtures.py`). No credential involved.
_PLACEHOLDER_KEY = "unit" + "-test-" + "placeholder"


# ── SDK-shaped exception doubles ─────────────────────────────────────────────
class _StatusError(Exception):
    """OpenAI/Anthropic shape: an integer `.status_code`."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class _GenaiError(Exception):
    """google-genai shape: an integer `.code` and a string `.status`."""

    def __init__(self, code: int, status: str = "ERROR") -> None:
        super().__init__(f"{code} {status}.")
        self.code = code
        self.status = status


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _ResponseError(Exception):
    """httpx `HTTPStatusError` shape: the status hangs off `.response`."""

    def __init__(self, status_code: int) -> None:
        super().__init__("http status error")
        self.response = _Response(status_code)


class APIConnectionError(Exception):
    """Name-shaped like the SDK class; carries no status because no response came."""


class APITimeoutError(APIConnectionError):
    pass


class ConnectError(Exception):
    pass


class ReadTimeout(Exception):
    pass


# ── the classifier ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        # Permanent: the identical request is rejected identically.
        (400, False),  # invalid request / INVALID_ARGUMENT
        (401, False),  # authentication
        (403, False),  # authorization
        (404, False),  # deterministic not-found
        (413, False),  # request too large
        (422, False),  # semantic validation
        # Retryable. 408 and 409 are *not* an oversight: OpenAI and Anthropic both
        # retry them in their own `_should_retry`, documenting them as request
        # timeout and lock timeout — conditions an identical retry does clear.
        (408, True),
        (409, True),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (529, True),  # Anthropic overloaded
    ],
)
def test_status_decides_retryability(status, retryable):
    assert is_retryable_provider_error(_StatusError(status)) is retryable
    assert is_retryable_provider_error(_GenaiError(status)) is retryable
    assert is_retryable_provider_error(_ResponseError(status)) is retryable


@pytest.mark.parametrize(
    "exc", [APIConnectionError(), APITimeoutError(), ConnectError(), ReadTimeout()]
)
def test_transport_failures_are_retryable(exc):
    """No response arrived, so there is no status — and a retry may well connect."""
    assert status_code_of(exc) is None
    assert is_retryable_provider_error(exc) is True


@pytest.mark.parametrize("exc", [TimeoutError(), ConnectionResetError()])
def test_builtin_transport_failures_are_retryable(exc):
    assert is_retryable_provider_error(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bad value"),
        TypeError("bad type"),
        KeyError("missing"),
        AttributeError("nope"),
        RuntimeError("something local"),
        Exception("unclassified"),
    ],
)
def test_unknown_and_local_errors_fail_fast(exc):
    """The deliberate default.

    Retrying an unrecognised exception is what produced the original defect: a
    programming or configuration error is deterministic, so extra attempts only
    delay the fallback that was going to happen anyway.
    """
    assert is_retryable_provider_error(exc) is False


def test_status_beats_a_transport_sounding_class_name():
    """A 400 stays permanent even when the class name contains a transport marker."""

    class ConnectionBadRequestError(Exception):
        def __init__(self) -> None:
            super().__init__("400")
            self.status_code = 400

    assert is_retryable_provider_error(ConnectionBadRequestError()) is False


# ── status extraction edge cases ─────────────────────────────────────────────
def test_string_error_codes_are_not_mistaken_for_a_status():
    """OpenAI's `APIError.code` is a *string* slug alongside the integer status."""

    class _Both(Exception):
        status_code = 400
        code = "invalid_api_key"

    assert status_code_of(_Both()) == 400


def test_a_non_http_code_attribute_is_ignored():
    class _Exit(Exception):
        code = 2  # outside 100..599

    assert status_code_of(_Exit()) is None
    assert is_retryable_provider_error(_Exit()) is False


def test_boolean_code_is_not_read_as_a_status():
    class _Flag(Exception):
        code = True  # bool is an int subclass

    assert status_code_of(_Flag()) is None


# ── the envelope ─────────────────────────────────────────────────────────────
class _CountingProvider(BaseNetworkProvider):
    """Counts `_invoke` calls; raises a scripted error N times, then succeeds."""

    name = "counting"

    def __init__(self, *, error: Exception, fail_times: int = 99, max_retries: int = 2) -> None:
        super().__init__(
            api_key=_PLACEHOLDER_KEY, model="m", timeout=1.0, max_retries=max_retries
        )
        self._error = error
        self._fail_times = fail_times
        self.calls = 0

    def _invoke(self, *, system: str, user: str, task: str) -> str:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return "ok"


def _run(provider: _CountingProvider):
    return provider.complete(system="S", user="U")


@pytest.mark.parametrize(
    ("label", "error"),
    [
        ("400 invalid argument", _StatusError(400)),
        ("401 authentication", _StatusError(401)),
        ("403 authorization", _StatusError(403)),
        ("404 not found", _StatusError(404)),
        ("gemini 400 INVALID_ARGUMENT", _GenaiError(400, "INVALID_ARGUMENT")),
        ("ValueError", ValueError("bad value")),
        ("TypeError", TypeError("bad type")),
        ("unknown exception", Exception("unclassified")),
    ],
)
def test_permanent_failures_are_attempted_exactly_once(label, error):
    provider = _CountingProvider(error=error, max_retries=2)
    with pytest.raises(LLMUnavailableError):
        _run(provider)
    assert provider.calls == 1, f"{label} was retried"


@pytest.mark.parametrize(
    ("label", "error"),
    [
        ("connection failure", APIConnectionError()),
        ("timeout", APITimeoutError()),
        ("429 rate limit", _StatusError(429)),
        ("500 internal", _StatusError(500)),
        ("502 bad gateway", _StatusError(502)),
        ("503 unavailable", _StatusError(503)),
        ("gemini 429", _GenaiError(429, "RESOURCE_EXHAUSTED")),
    ],
)
def test_a_transient_failure_is_retried_and_the_call_succeeds(label, error):
    provider = _CountingProvider(error=error, fail_times=1, max_retries=2)
    assert _run(provider) == "ok"
    assert provider.calls == 2, f"{label} did not retry exactly once"


def test_transient_exhaustion_uses_the_full_budget_then_degrades():
    """`max_retries` is *additional* attempts, so 2 means at most 3 calls."""
    provider = _CountingProvider(error=_StatusError(503), max_retries=2)
    with pytest.raises(LLMUnavailableError):
        _run(provider)
    assert provider.calls == 3


def test_configured_retry_count_is_unchanged_by_classification():
    provider = _CountingProvider(error=_StatusError(503), max_retries=1)
    with pytest.raises(LLMUnavailableError):
        _run(provider)
    assert provider.calls == 2

    provider = _CountingProvider(error=_StatusError(503), max_retries=0)
    with pytest.raises(LLMUnavailableError):
        _run(provider)
    assert provider.calls == 1


def test_a_successful_call_is_made_exactly_once():
    provider = _CountingProvider(error=_StatusError(503), fail_times=0)
    assert _run(provider) == "ok"
    assert provider.calls == 1


def test_both_failure_modes_normalise_to_the_same_fallback_signal():
    """Invariant #4 is unchanged: the caller still sees one error type either way.

    Classification changes *how many attempts* a failure costs, never what the
    orchestrator observes — so the deterministic heuristic fallback is untouched.
    """
    permanent = _CountingProvider(error=_StatusError(400))
    transient = _CountingProvider(error=_StatusError(503))
    for provider in (permanent, transient):
        with pytest.raises(LLMUnavailableError):
            _run(provider)
    assert (permanent.calls, transient.calls) == (1, 3)


def test_a_missing_api_key_still_fails_before_any_attempt():
    provider = _CountingProvider(error=_StatusError(503))
    provider._api_key = ""
    with pytest.raises(LLMUnavailableError):
        _run(provider)
    assert provider.calls == 0


# ── the real SDK classes, when the optional extras are installed ─────────────
# `requirements-dev.txt` carries no provider SDK, so these skip in the default
# environment. They exist so the shapes reconstructed above can be checked against
# the genuine article wherever the extras are present.
def _sdk(name: str):
    return pytest.importorskip(name, reason=f"optional extra {name!r} not installed")


@pytest.mark.parametrize("sdk_name", ["openai", "anthropic"])
@pytest.mark.parametrize(
    ("cls_name", "status", "retryable"),
    [
        ("BadRequestError", 400, False),
        ("AuthenticationError", 401, False),
        ("PermissionDeniedError", 403, False),
        ("NotFoundError", 404, False),
        ("ConflictError", 409, True),
        ("RateLimitError", 429, True),
        ("InternalServerError", 500, True),
    ],
)
def test_real_openai_and_anthropic_status_errors(sdk_name, cls_name, status, retryable):
    sdk = _sdk(sdk_name)
    httpx = _sdk("httpx")
    cls = getattr(sdk, cls_name, None)
    if cls is None:  # pragma: no cover — SDK surface drift
        pytest.skip(f"{sdk_name} has no {cls_name}")
    request = httpx.Request("POST", "https://api.example/v1/x")
    response = httpx.Response(status, request=request, json={"error": {"message": "m"}})
    exc = cls("m", response=response, body=None)
    assert status_code_of(exc) == status
    assert is_retryable_provider_error(exc) is retryable


@pytest.mark.parametrize("sdk_name", ["openai", "anthropic"])
def test_real_transport_errors_are_retryable(sdk_name):
    sdk = _sdk(sdk_name)
    httpx = _sdk("httpx")
    request = httpx.Request("POST", "https://api.example/v1/x")
    for cls_name in ("APIConnectionError", "APITimeoutError"):
        exc = getattr(sdk, cls_name)(request=request)
        assert status_code_of(exc) is None
        assert is_retryable_provider_error(exc) is True, cls_name


@pytest.mark.parametrize(
    ("code", "status", "retryable"),
    [
        (400, "INVALID_ARGUMENT", False),
        (401, "UNAUTHENTICATED", False),
        (403, "PERMISSION_DENIED", False),
        (404, "NOT_FOUND", False),
        (429, "RESOURCE_EXHAUSTED", True),
        (500, "INTERNAL", True),
        (503, "UNAVAILABLE", True),
    ],
)
def test_real_genai_errors(code, status, retryable):
    _sdk("google.genai")
    from google.genai import errors as genai_errors

    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    exc = cls(code, {"error": {"code": code, "message": "m", "status": status}})
    assert status_code_of(exc) == code
    assert is_retryable_provider_error(exc) is retryable
