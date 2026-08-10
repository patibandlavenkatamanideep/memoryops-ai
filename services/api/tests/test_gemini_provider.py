"""The Gemini adapter's contract, pinned across the `google-genai` migration.

`google-genai` is an optional extra and is absent from `requirements-dev.txt`, so CI
runs these without it installed. Every test therefore injects a fake `google.genai`
into `sys.modules` rather than importing the real SDK — which also keeps them
offline, key-free and deterministic. No test here makes a network call.

The migration replaced a retired SDK, and two of its differences are behavioural
rather than cosmetic; both are asserted below:

* `HttpOptions.timeout` is in **milliseconds**, where the old
  `request_options={"timeout": …}` took seconds. Forwarding the configured seconds
  unchanged would turn an 8-second budget into 8 milliseconds.
* the new client speaks HTTP via `httpx` instead of gRPC, which is what makes
  provider traffic recordable by the VCR/pytest-recording stack.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import types as pytypes
from pathlib import Path

import pytest

from app.llm.base import LLMUnavailableError
from app.llm.gemini_provider import GeminiProvider

_PROVIDER_SRC = Path(__file__).resolve().parents[1] / "app" / "llm" / "gemini_provider.py"

#: Resolved at import time, before any fixture can shadow `google.genai`.
_HAS_REAL_SDK = importlib.util.find_spec("google.genai") is not None


class _Recorder(dict):
    """Captures what the adapter passed to the SDK."""

    calls: int = 0


@pytest.fixture
def gemini_sdk(monkeypatch):
    """Install a fake `google.genai`; return the recorder.

    Behaviour is driven by attributes set on the returned recorder *before* the call:
    ``text`` (response text), ``fail_times`` (raise N times, then succeed).
    """
    rec = _Recorder()
    rec["text"] = "ok"
    rec["fail_times"] = 0

    class _Response:
        def __init__(self, text):
            self.text = text

    class _Models:
        def generate_content(self, **kwargs):
            rec["generate_content"] = kwargs
            rec.calls += 1
            if rec.calls <= rec["fail_times"]:
                raise RuntimeError("transient upstream failure")
            return _Response(rec["text"])

    class _Client:
        def __init__(self, **kwargs):
            rec["client_kwargs"] = kwargs
            self.models = _Models()

    def _http_options(**kw):
        rec["http_options"] = kw
        return kw

    def _generate_config(**kw):
        rec["generate_config"] = kw
        return kw

    types_mod = pytypes.ModuleType("google.genai.types")
    types_mod.HttpOptions = _http_options
    types_mod.GenerateContentConfig = _generate_config

    genai_mod = pytypes.ModuleType("google.genai")
    genai_mod.Client = _Client
    genai_mod.types = types_mod

    google_mod = pytypes.ModuleType("google")
    google_mod.genai = genai_mod

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return rec


def _provider(**kw) -> GeminiProvider:
    defaults = {
        "api_key": "test-key-not-real",
        "model": "gemini-2.5-flash",
        "timeout": 8.0,
        "max_retries": 0,
    }
    return GeminiProvider(**{**defaults, **kw})


# ── construction and wiring ─────────────────────────────────────────────────
def test_provider_name_is_gemini():
    assert _provider().name == "gemini"


def test_configured_model_is_used(gemini_sdk):
    _provider(model="gemini-2.0-flash").complete(system="S", user="U")
    assert gemini_sdk["generate_content"]["model"] == "gemini-2.0-flash"


def test_prompt_reaches_the_client(gemini_sdk):
    _provider().complete(system="SYSTEM-PROMPT", user="USER-MESSAGE")
    assert gemini_sdk["generate_content"]["contents"] == "USER-MESSAGE"
    assert gemini_sdk["generate_config"]["system_instruction"] == "SYSTEM-PROMPT"


def test_temperature_is_zero_for_determinism(gemini_sdk):
    _provider().complete(system="S", user="U")
    assert gemini_sdk["generate_config"]["temperature"] == 0


def test_api_key_is_passed_to_the_client(gemini_sdk):
    _provider(api_key="key-abc").complete(system="S", user="U")
    assert gemini_sdk["client_kwargs"]["api_key"] == "key-abc"


# ── the millisecond trap ────────────────────────────────────────────────────
@pytest.mark.parametrize(("seconds", "expected_ms"), [(8.0, 8000), (1.5, 1500), (30.0, 30000)])
def test_timeout_is_converted_from_seconds_to_milliseconds(gemini_sdk, seconds, expected_ms):
    """`HttpOptions.timeout` is milliseconds; the settings value is seconds.

    Forwarding seconds unchanged would make an 8-second budget an 8-millisecond one
    and fail every call — a silent, total provider outage that degrades to the
    heuristic while looking like a provider problem.
    """
    _provider(timeout=seconds).complete(system="S", user="U")
    assert gemini_sdk["http_options"]["timeout"] == expected_ms


# ── response parsing ────────────────────────────────────────────────────────
def test_text_response_is_returned(gemini_sdk):
    gemini_sdk["text"] = '{"memories": []}'
    assert _provider().complete(system="S", user="U") == '{"memories": []}'


@pytest.mark.parametrize("empty", [None, ""])
def test_empty_response_becomes_empty_string(gemini_sdk, empty):
    """`resp.text` can be None; the contract returns `str`, never None."""
    gemini_sdk["text"] = empty
    assert _provider().complete(system="S", user="U") == ""


# ── error, key and retry handling ───────────────────────────────────────────
def test_missing_api_key_raises_unavailable_without_calling_the_sdk(gemini_sdk):
    with pytest.raises(LLMUnavailableError):
        _provider(api_key="").complete(system="S", user="U")
    assert gemini_sdk.calls == 0


def test_sdk_failure_is_normalised_to_llm_unavailable(gemini_sdk):
    """Invariant #4: a provider outage degrades, never crashes the chat path."""
    gemini_sdk["fail_times"] = 99
    with pytest.raises(LLMUnavailableError):
        _provider().complete(system="S", user="U")


def test_transient_failures_are_retried_per_the_base_contract(gemini_sdk):
    """`max_retries` is *additional* attempts, so 2 means up to 3 calls."""
    gemini_sdk["fail_times"] = 2
    assert _provider(max_retries=2).complete(system="S", user="U") == "ok"
    assert gemini_sdk.calls == 3


def test_retries_are_bounded(gemini_sdk):
    gemini_sdk["fail_times"] = 99
    with pytest.raises(LLMUnavailableError):
        _provider(max_retries=1).complete(system="S", user="U")
    assert gemini_sdk.calls == 2


# ── migration guards ────────────────────────────────────────────────────────
def test_no_active_legacy_sdk_import_remains():
    """Prose about the retired SDK is fine; an actual import is not.

    Parsed rather than grepped — the module docstring names `google.generativeai`
    while explaining why it was replaced, and a substring search would fail on the
    file's own explanation.
    """
    tree = ast.parse(_PROVIDER_SRC.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported += [f"{node.module}.{a.name}" for a in node.names]
    assert not any(n.startswith("google.generativeai") for n in imported), imported
    assert any("genai" in n for n in imported), imported


@pytest.mark.skipif(not _HAS_REAL_SDK, reason="google-genai not installed (optional extra)")
def test_real_sdk_uses_an_http_transport_vcr_can_record():
    """The reason for the migration, asserted against the real SDK when present.

    gRPC cannot be recorded by VCR/pytest-recording, so provider evidence could not
    be replayed in CI. Skipped when the optional extra is absent, which is the CI
    default.
    """
    import inspect

    import google.genai._api_client as api_client

    src = inspect.getsource(api_client)
    assert "httpx" in src, "google-genai sync client is expected to use httpx"
    assert "class SyncHttpxClient(httpx.Client)" in src
