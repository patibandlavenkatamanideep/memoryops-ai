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

    # Observability (v0.13, ADR-015). Process-wide Prometheus metrics exposition at
    # GET /metrics. Content-free, low-cardinality, no new dependency. ON by default;
    # toggle with MEMORYOPS_METRICS_ENABLED. Distinct from the per-tenant business
    # metrics JSON at GET /api/metrics.
    metrics_enabled: bool = True

    # Economics (v1.2, ADR-016). Advisory per-request token + cost estimation,
    # surfaced on the chat response + Prometheus counters. Costs are list-price
    # estimates, never billing; unknown/stub models are unpriced ($0). Operators
    # override per-model prices with MEMORYOPS_PRICING_OVERRIDES (JSON, e.g.
    # '{"gpt-4o-mini":{"input":0.15,"output":0.6}}'). USD per 1M tokens.
    pricing_overrides_json: str = ""

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
    # Deletion compaction (v0.7, ADR-011). Only already soft-deleted memory is
    # eligible, and only after it has been deleted for at least this many days
    # (a retention/grace window before retrievable content + vector material are
    # cleared). Default 0 = eligible as soon as it is deleted. Compaction never
    # touches active/archived rows and never resurrects deleted memory.
    workers_compaction_min_age_days: int = 0

    # Retention policies + legal hold + consent-aware memory (v0.10, ADR-013).
    # The retention worker evaluates active memory against a named policy pack
    # (sensitivity tier → retention window) and soft-deletes memory whose window
    # has elapsed or whose consent was withdrawn/expired — UNLESS it is on legal
    # hold, pinned, or protected (those override and block all forgetting). The
    # worker only soft-deletes; the existing deletion-verification + compaction
    # workers then handle the deleted rows. OFF by default so an unconfigured
    # run never auto-deletes; opt in per deployment.
    workers_retention_enabled: bool = False
    retention_default_policy: str = "default"  # default | strict | extended

    # Worker runtime / scheduled lifecycle orchestration (v0.8, ADR-012). The
    # orchestrator runs lifecycle jobs on a schedule for explicit scopes, with a
    # lease (lock) to prevent duplicate concurrent runs, a retry/backoff policy,
    # persisted run history, and dead-letter records for exhausted retries.
    worker_interval_seconds: int = 60
    worker_lease_ttl_seconds: int = 300
    worker_max_attempts: int = 3
    worker_backoff_base_seconds: float = 1.0
    worker_backoff_factor: float = 2.0
    worker_backoff_max_seconds: float = 30.0
    # Explicit scopes the scheduler runs, "tenant:user" comma-separated. Scope
    # enumeration stays explicit (no unbounded cross-tenant scan) — see ADR-010/012.
    worker_scopes: str = "tenant_demo:user_demo"
    worker_run_history_limit: int = 500

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
    if (val := os.getenv("MEMORYOPS_METRICS_ENABLED")) is not None:
        overrides["metrics_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_PRICING_OVERRIDES")) is not None:
        overrides["pricing_overrides_json"] = val
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
    # v0.8 worker runtime knobs (ADR-012). Operator-facing public toggles.
    if (val := os.getenv("MEMORYOPS_WORKER_INTERVAL_SECONDS")) is not None:
        with contextlib.suppress(ValueError):
            overrides["worker_interval_seconds"] = int(val)
    if (val := os.getenv("MEMORYOPS_WORKER_SCOPES")) is not None:
        overrides["worker_scopes"] = val
    return Settings(**overrides)
