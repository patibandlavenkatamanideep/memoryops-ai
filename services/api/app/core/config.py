"""Typed application settings (pydantic-settings).

All configuration flows through this single object so behavior is explicit and
testable. Environment variables override defaults; a local .env is honored.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    service_name: str = "memoryops-api"
    log_level: str = "INFO"

    # Storage backend: "memory" runs with no infra (default for dev/tests),
    # "postgres" uses SQLAlchemy + pgvector.
    storage: Literal["memory", "postgres"] = "memory"
    database_url: str = "postgresql+psycopg://memoryops:memoryops@localhost:5432/memoryops"

    redis_url: str = "redis://localhost:6379/0"

    # LLM + embeddings. "stub" requires no API keys and keeps the system fully
    # functional offline (graceful degradation, invariant #4). "heuristic" is a
    # back-compat alias for "stub". Provider adapters (v0.4, ADR-008) are used
    # only when their API key is present; otherwise selection degrades to stub.
    llm_provider: Literal["stub", "heuristic", "openai", "anthropic", "gemini"] = "stub"
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-haiku-4-5-20251001"
    gemini_model: str = "gemini-1.5-flash"

    # Structured memory intelligence knobs (v0.4). Defaults keep LLM output
    # advisory and always recoverable: validate structured output, and fall back
    # to the deterministic heuristic on any invalid/failed provider call. The LLM
    # never overrides the deterministic policy broker (ADR-003/008).
    llm_require_structured_output: bool = True
    llm_fallback_to_heuristic: bool = True
    llm_max_retries: int = 2

    # "stub" is the deterministic default; "heuristic" is kept as a back-compat
    # alias for the same provider. "openai" is used only when a key is present.
    embeddings_provider: Literal["stub", "heuristic", "openai"] = "stub"
    embedding_dim: int = 1536
    openai_embedding_model: str = "text-embedding-3-small"

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # Optional context compression at the LLM boundary (v0.2.1, ADR-007).
    # "none" (default) is fully transparent; "headroom" uses the optional adapter
    # and degrades to no-op on any failure. Compression runs only AFTER policy +
    # governance + composition — never before the policy broker.
    context_compression: Literal["none", "headroom"] = "none"
    compression_require_policy_cleared: bool = True
    headroom_mode: Literal["library", "proxy", "mcp"] = "library"
    headroom_output_shaper: bool = False

    # Background memory lifecycle workers (v0.6, ADR-010). Workers run outside the
    # chat path; these are policy thresholds, not request knobs. Defaults are
    # conservative so a default run touches little. Reflection is proposal-only
    # and OFF by default (it never writes/deletes memory; see workers/reflection).
    workers_decay_age_days: int = 90
    workers_decay_min_confidence: float = 0.3
    workers_decay_importance_floor: int = 1
    workers_decay_importance_step: int = 2
    workers_archive_age_days: int = 180
    workers_archive_recent_use_days: int = 30
    workers_conflict_scan_max_memories: int = 200
    workers_reflection_enabled: bool = False
    workers_reflection_min_cluster_size: int = 5
    workers_reflection_max_importance: int = 3

    # Reliability knobs (used by core.reliability).
    llm_timeout_seconds: float = 8.0
    retrieval_timeout_seconds: float = 3.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    # MEMORYOPS_STORAGE is the documented public knob; map it onto `storage`.
    import contextlib
    import os

    overrides = {}
    if (val := os.getenv("MEMORYOPS_STORAGE")) in ("memory", "postgres"):
        overrides["storage"] = val
    if (val := os.getenv("MEMORYOPS_EMBEDDING_PROVIDER")) in ("stub", "heuristic", "openai"):
        overrides["embeddings_provider"] = val
    if (val := os.getenv("MEMORYOPS_CONTEXT_COMPRESSION")) in ("none", "headroom"):
        overrides["context_compression"] = val
    if (val := os.getenv("MEMORYOPS_COMPRESSION_REQUIRE_POLICY_CLEARED")) is not None:
        overrides["compression_require_policy_cleared"] = val.lower() not in ("0", "false", "no")
    # v0.4 LLM provider knobs (ADR-008). MEMORYOPS_LLM_PROVIDER is the public knob.
    if (val := os.getenv("MEMORYOPS_LLM_PROVIDER")) in (
        "stub", "heuristic", "openai", "anthropic", "gemini"
    ):
        overrides["llm_provider"] = val
    if (val := os.getenv("MEMORYOPS_LLM_REQUIRE_STRUCTURED_OUTPUT")) is not None:
        overrides["llm_require_structured_output"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_LLM_FALLBACK_TO_HEURISTIC")) is not None:
        overrides["llm_fallback_to_heuristic"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_LLM_MAX_RETRIES")) is not None:
        with contextlib.suppress(ValueError):
            overrides["llm_max_retries"] = int(val)
    if (val := os.getenv("MEMORYOPS_LLM_TIMEOUT_SECONDS")) is not None:
        with contextlib.suppress(ValueError):
            overrides["llm_timeout_seconds"] = float(val)
    # v0.6 worker knobs (ADR-010). Reflection is the only one with a public,
    # documented toggle; other thresholds are configured via their field names.
    if (val := os.getenv("MEMORYOPS_WORKERS_REFLECTION")) is not None:
        overrides["workers_reflection_enabled"] = val.lower() not in ("0", "false", "no")
    return Settings(**overrides)
