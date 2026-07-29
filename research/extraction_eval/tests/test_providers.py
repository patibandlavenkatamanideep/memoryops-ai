"""Provider contract tests (offline, no keys)."""

from __future__ import annotations

import pathlib

from research.extraction_eval.errors import ErrorClass, is_retryable
from research.extraction_eval.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAIProvider,
    StubProvider,
    build_provider,
)
from research.extraction_eval.providers.base import parse_json_output
from research.extraction_eval.schema import ExtractionOutput

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"

_CONV = [{"turn_id": "t1", "role": "user", "content": "Remember I prefer metric units."}]


def test_stub_conforms_to_schema():
    r = StubProvider().extract(prompt="", conversation=_CONV, target_turn_id="t1")
    assert r.ok and isinstance(r.output, ExtractionOutput)
    assert r.api_model_id == "stub" and not r.error_class


def test_stub_noop_on_chitchat():
    conv = [{"turn_id": "t1", "role": "user", "content": "haha nice"}]
    r = StubProvider().extract(prompt="", conversation=conv, target_turn_id="t1")
    assert r.ok and r.output.is_noop


def test_each_adapter_normalises_valid_fixture():
    for name, fixture in (("openai", "openai_valid.json"), ("gemini", "gemini_valid.json"),
                          ("anthropic", "anthropic_valid.json")):
        provider = build_provider(name, "model-x")
        out, err, _ = provider.parse((FIXTURES / fixture).read_text())
        assert err is None, (name, err)
        assert isinstance(out, ExtractionOutput) and len(out.memories) == 1


def test_anthropic_fenced_json_is_stripped():
    out, err, _ = AnthropicProvider("m").parse((FIXTURES / "anthropic_valid.json").read_text())
    assert err is None and out.memories[0].memory_type == "constraint"


def test_invalid_json_classified():
    out, err, _ = OpenAIProvider("m").parse((FIXTURES / "invalid_json.txt").read_text())
    assert out is None and err is ErrorClass.structured_output_error


def test_schema_mismatch_classified():
    out, err, _ = GeminiProvider("m").parse((FIXTURES / "schema_invalid.json").read_text())
    assert out is None and err is ErrorClass.schema_validation_error


def test_empty_response_classified():
    out, err, _ = parse_json_output("")
    assert out is None and err is ErrorClass.empty_response


def test_refusal_and_truncation_classified():
    from research.extraction_eval.providers.anthropic import _result_from_raw as ant
    from research.extraction_eval.providers.openai import _result_from_raw as oai

    assert oai("", OpenAIProvider("m"), "length").error_class == ErrorClass.truncation.value
    assert oai("", OpenAIProvider("m"), "content_filter").error_class == ErrorClass.refusal.value
    assert ant("", AnthropicProvider("m"), "max_tokens").error_class == ErrorClass.truncation.value


def test_content_failures_are_not_retryable():
    for ec in (ErrorClass.structured_output_error, ErrorClass.schema_validation_error,
               ErrorClass.refusal, ErrorClass.truncation, ErrorClass.empty_response):
        assert not is_retryable(ec)
    for ec in (ErrorClass.rate_limit_error, ErrorClass.provider_error, ErrorClass.network_error):
        assert is_retryable(ec)


def test_network_adapters_unavailable_without_key(monkeypatch):
    for env in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert OpenAIProvider("m").available() is False
    assert GeminiProvider("m").available() is False
    assert AnthropicProvider("m").available() is False


def test_provider_does_not_store_credentials():
    # The key is read from env at call time, never held on the object.
    p = OpenAIProvider("m")
    assert not any("key" in k.lower() for k in vars(p))
