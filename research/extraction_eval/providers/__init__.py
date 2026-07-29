"""Provider registry — build a provider by name from the experiment config.

Never falls back between providers. Network adapters are import-guarded so the module
loads (and the stub runs) with no SDKs installed.
"""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Provider, ProviderResult, parse_json_output
from .gemini import GeminiProvider
from .openai import OpenAIProvider
from .stub import StubProvider

__all__ = [
    "Provider",
    "ProviderResult",
    "parse_json_output",
    "StubProvider",
    "GeminiProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "build_provider",
]

_NETWORK = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
}


def build_provider(name: str, model_id: str, *, max_retries: int = 3):
    """Construct a provider adapter by name. ``model_id`` is ignored for the stub."""
    if name == "stub":
        return StubProvider()
    if name in _NETWORK:
        return _NETWORK[name](model_id, max_retries=max_retries)
    raise ValueError(f"unknown provider {name!r}; expected stub|gemini|openai|anthropic")
