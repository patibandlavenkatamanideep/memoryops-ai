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

    # Public eval trigger (security). POST /api/evals/run executes the full eval
    # harness on demand — a denial-of-wallet / compute-abuse vector if exposed
    # unauthenticated on a public deployment. OFF by default: the trigger returns
    # 403 unless an operator explicitly opts in with MEMORYOPS_PUBLIC_EVALS=true.
    # GET /api/evals/latest serves a server-cached result and is always available.
    public_evals: bool = False
    # Minimum seconds between cached-result regenerations for GET /api/evals/latest.
    evals_cache_ttl_seconds: int = 300

    # Request hygiene + rate limiting (P2.4). Dependency-free, in-process (fits the
    # single-instance Railway deploy); protects the public demo from denial-of-wallet
    # and oversized bodies. All no-throw. Tune per deployment / put a real gateway
    # limiter in front for multi-instance.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120            # per client IP, all /api/* routes
    rate_limit_chat_per_minute: int = 30        # stricter, per tenant/IP on /api/chat
    rate_limit_evals_per_minute: int = 6        # stricter still on /api/evals/*
    max_request_bytes: int = 65536              # 64 KB body cap on /api/* → 413
    max_message_chars: int = 8000               # ChatRequest.message / memory content

    # Observability (v0.13, ADR-015). Process-wide Prometheus metrics exposition at
    # GET /metrics. Content-free, low-cardinality, no new dependency. ON by default;
    # toggle with MEMORYOPS_METRICS_ENABLED. Distinct from the per-tenant business
    # metrics JSON at GET /api/metrics.
    metrics_enabled: bool = True

    # Distributed tracing (v1.8, ADR-022). In-process, content-free span recording
    # for the memory lifecycle (write/read/admission/workers/deletion), exposed at
    # GET /api/traces and correlated by request/job id. Dependency-free by default;
    # if the OpenTelemetry SDK is installed and `otel_enabled`, spans also export to
    # your real backend. Toggle with MEMORYOPS_TRACING_ENABLED / MEMORYOPS_OTEL_ENABLED.
    tracing_enabled: bool = True
    otel_enabled: bool = False

    # Economics (v1.2, ADR-016). Advisory per-request token + cost estimation,
    # surfaced on the chat response + Prometheus counters. Costs are list-price
    # estimates, never billing; unknown/stub models are unpriced ($0). Operators
    # override per-model prices with MEMORYOPS_PRICING_OVERRIDES (JSON, e.g.
    # '{"gpt-4o-mini":{"input":0.15,"output":0.6}}'). USD per 1M tokens.
    pricing_overrides_json: str = ""

    # Context Admission Gate + Memory Usage Trace (v1.3, ADR-017). The gate runs
    # after rank / before compose and decides, per memory, whether it is *allowed*
    # into context (not merely relevant) — emitting an explainable admission trace.
    # Conservative defaults preserve behavior: deleted/archived/expired/
    # consent-withdrawn/wrong-tenant are blocked (all defense-in-depth; the
    # repository already filters non-active rows), while the two stricter gates
    # below are OFF by default. `admission_gate_enabled=False` runs the gate in
    # observe-only (shadow) mode: decisions are still traced but nothing is removed.
    admission_gate_enabled: bool = True
    memory_trace_enabled: bool = True
    # Opt-in stricter gates (default OFF → behavior-preserving):
    admission_block_sensitive: bool = False  # block sensitivity='high' from context
    admission_min_score: float = 0.0  # block ranked score below this (0 = disabled)

    # Recall Gate + Output Gate (v1.9, ADR-023). The Recall Gate admits a memory into
    # context only if its sensitivity is permitted for the request's `audience`
    # (default "private" = full clearance → no behavior change). The Output Gate
    # inspects the generated answer and redacts/refuses content that would disclose a
    # memory the gates blocked. Both ON by default but no-op unless there is something
    # to protect. `output_gate_mode` = redact | refuse.
    recall_gate_enabled: bool = True
    output_gate_enabled: bool = True
    output_gate_mode: Literal["redact", "refuse"] = "redact"

    # Storage backend: "memory" runs with no infra (default for dev/tests),
    # "postgres" uses SQLAlchemy + pgvector.
    storage: Literal["memory", "postgres"] = "memory"

    # Pluggable vector-search backend (v1.7, ADR-021). The one store-specific part
    # of retrieval; the repository stays authoritative for governance. "memory" is
    # dependency-free (default). External backends (qdrant|lancedb|weaviate) are
    # constructed only when selected and degrade to keyword-only if unreachable.
    vector_index: Literal["memory", "qdrant", "lancedb", "weaviate"] = "memory"
    vector_index_url: str = ""  # qdrant/weaviate endpoint
    vector_index_uri: str = "./.lancedb"  # lancedb path/uri
    vector_index_api_key: str = ""
    vector_index_collection: str = "memoryops"
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

    # Auth + authorization adapters (v1.6, ADR-020). Identity-neutral: MemoryOps
    # verifies an identity an upstream issuer minted and scopes every operation to
    # it. OFF by default ("none" trusts the caller, as before) → no behavior change.
    #   trusted_header — an authenticated upstream proxy injects tenant/user headers
    #   jwt            — MemoryOps verifies a bearer JWT and maps claims to tenant/user
    auth_mode: Literal["none", "trusted_header", "jwt"] = "none"
    auth_tenant_header: str = "X-MemoryOps-Tenant"
    auth_user_header: str = "X-MemoryOps-User"
    auth_jwt_key: str = ""  # HS* shared secret or RS* PEM public key
    auth_jwt_algorithms: str = "HS256"  # comma-separated allow-list
    auth_jwt_tenant_claim: str = "tenant_id"  # dotted path ok (e.g. app_metadata.tenant_id)
    auth_jwt_user_claim: str = "sub"
    auth_jwt_audience: str = ""
    auth_jwt_issuer: str = ""
    # Optional JWKS endpoint (RS*/ES*). When set, the signing key is fetched + cached
    # from the issuer's JWKS instead of using a static auth_jwt_key. Needs pyjwt[crypto].
    auth_jwt_jwks_url: str = ""

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
    if (val := os.getenv("MEMORYOPS_PUBLIC_EVALS")) is not None:
        overrides["public_evals"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_RATE_LIMIT_ENABLED")) is not None:
        overrides["rate_limit_enabled"] = val.lower() not in ("0", "false", "no")
    for env_name, field_name in (
        ("MEMORYOPS_RATE_LIMIT_PER_MINUTE", "rate_limit_per_minute"),
        ("MEMORYOPS_RATE_LIMIT_CHAT_PER_MINUTE", "rate_limit_chat_per_minute"),
        ("MEMORYOPS_RATE_LIMIT_EVALS_PER_MINUTE", "rate_limit_evals_per_minute"),
        ("MEMORYOPS_MAX_REQUEST_BYTES", "max_request_bytes"),
        ("MEMORYOPS_MAX_MESSAGE_CHARS", "max_message_chars"),
    ):
        if (val := os.getenv(env_name)) is not None:
            with contextlib.suppress(ValueError):
                overrides[field_name] = int(val)
    if (val := os.getenv("MEMORYOPS_TRACING_ENABLED")) is not None:
        overrides["tracing_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_OTEL_ENABLED")) is not None:
        overrides["otel_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_PRICING_OVERRIDES")) is not None:
        overrides["pricing_overrides_json"] = val
    # v1.2 Context Admission Gate knobs (ADR-017). Public operator toggles.
    if (val := os.getenv("MEMORYOPS_ADMISSION_GATE")) is not None:
        overrides["admission_gate_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_MEMORY_TRACE")) is not None:
        overrides["memory_trace_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_ADMISSION_BLOCK_SENSITIVE")) is not None:
        overrides["admission_block_sensitive"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_ADMISSION_MIN_SCORE")) is not None:
        with contextlib.suppress(ValueError):
            overrides["admission_min_score"] = float(val)
    # v1.9 Recall Gate + Output Gate knobs (ADR-023). Public operator toggles.
    if (val := os.getenv("MEMORYOPS_RECALL_GATE")) is not None:
        overrides["recall_gate_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_OUTPUT_GATE")) is not None:
        overrides["output_gate_enabled"] = val.lower() not in ("0", "false", "no")
    if (val := os.getenv("MEMORYOPS_OUTPUT_GATE_MODE")) in ("redact", "refuse"):
        overrides["output_gate_mode"] = val
    if (val := os.getenv("MEMORYOPS_STORAGE")) in ("memory", "postgres"):
        overrides["storage"] = val
    # v1.7 pluggable vector index (ADR-021). Public operator toggles; default "memory".
    if (val := os.getenv("MEMORYOPS_VECTOR_INDEX")) in ("memory", "qdrant", "lancedb", "weaviate"):
        overrides["vector_index"] = val
    for env_name, field_name in (
        ("MEMORYOPS_VECTOR_INDEX_URL", "vector_index_url"),
        ("MEMORYOPS_VECTOR_INDEX_URI", "vector_index_uri"),
        ("MEMORYOPS_VECTOR_INDEX_API_KEY", "vector_index_api_key"),
        ("MEMORYOPS_VECTOR_INDEX_COLLECTION", "vector_index_collection"),
    ):
        if (val := os.getenv(env_name)) is not None:
            overrides[field_name] = val
    # v1.6 auth adapters (ADR-020). Public operator toggles; default "none".
    if (val := os.getenv("MEMORYOPS_AUTH_MODE")) in ("none", "trusted_header", "jwt"):
        overrides["auth_mode"] = val
    for env_name, field_name in (
        ("MEMORYOPS_AUTH_TENANT_HEADER", "auth_tenant_header"),
        ("MEMORYOPS_AUTH_USER_HEADER", "auth_user_header"),
        ("MEMORYOPS_AUTH_JWT_KEY", "auth_jwt_key"),
        ("MEMORYOPS_AUTH_JWT_ALGORITHMS", "auth_jwt_algorithms"),
        ("MEMORYOPS_AUTH_JWT_TENANT_CLAIM", "auth_jwt_tenant_claim"),
        ("MEMORYOPS_AUTH_JWT_USER_CLAIM", "auth_jwt_user_claim"),
        ("MEMORYOPS_AUTH_JWT_AUDIENCE", "auth_jwt_audience"),
        ("MEMORYOPS_AUTH_JWT_ISSUER", "auth_jwt_issuer"),
        ("MEMORYOPS_AUTH_JWT_JWKS_URL", "auth_jwt_jwks_url"),
    ):
        if (val := os.getenv(env_name)) is not None:
            overrides[field_name] = val
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
