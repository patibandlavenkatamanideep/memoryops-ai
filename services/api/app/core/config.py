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

    # Governance profile (paper study apparatus). "full" (default) is the frozen,
    # fully-governed system (== tag paper-v0.1-governance-runtime — no behavior change).
    # "disabled" produces the mechanism-matched *ungoverned* twin (S0-U) and is the
    # umbrella the Experiment-C ablations build on: it turns OFF policy-broker
    # enforcement, the admission/recall/output gates, transactional audit evidence, and
    # tombstone propagation, while keeping the SAME extractor, embeddings, storage,
    # retrieval, top-k, prompt, LLM, and temperature. Per-control flags below default
    # from the profile so a single ablation can be toggled independently. Off by
    # default → the frozen subject is untouched. See paper/protocol.md §3.
    governance_profile: Literal["full", "disabled"] = "full"
    # Resolved per-control switches (default True; the profile / env can force off).
    # Kept as real fields so an ablation can disable exactly one mechanism.
    govern_policy_enforcement: bool = True
    govern_transactional_evidence: bool = True
    govern_tombstone_propagation: bool = True

    # Deployment profile (v2.3). "dev" keeps the demo-friendly defaults (in-memory
    # store, auth off, open CORS) so the app runs with no infra. "production" turns
    # those same defaults into *fail-closed startup errors*: the app refuses to boot
    # until storage, auth, CORS, credentials, and the public-eval trigger are set to
    # safe values (see `production_readiness_errors`). Set MEMORYOPS_PROFILE=production
    # on real deployments. See docs/production-readiness.md.
    profile: Literal["dev", "production"] = "dev"

    # CORS allow-list. "*" (default) is fine for the public demo but is rejected under
    # the production profile. Comma-separated origins, e.g.
    # "https://app.example.com,https://admin.example.com".
    cors_allow_origins: str = "*"

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
    # Optional cross-tenant *operational* connection (a monitoring/BYPASSRLS
    # role) used only for global operator views like worker health. Unset by
    # default: operational aggregation is fail-closed and never reuses the
    # request-scoped, RLS-enforced connection. See docs/worker-runtime.md.
    operational_database_url: str = ""

    # NOTE: `redis_url` was removed. Redis was declared here, started by Compose, and
    # listed as a required Railway service, but no runtime code ever read it — no
    # client was imported anywhere in the repo. A declared-but-unused infrastructure
    # dependency is pure cost: another managed service to pay for, another health
    # check that can fail the deploy, and a misleading architecture diagram. Reinstate
    # it when something actually uses it (distributed rate limiting, job queueing,
    # caching, pub/sub, cross-replica coordination). `extra="ignore"` above means a
    # leftover REDIS_URL in an existing environment is harmlessly ignored.

    # LLM + embeddings. "stub" requires no API keys and keeps the system fully
    # functional offline (graceful degradation, invariant #4). "heuristic" is a
    # back-compat alias for "stub". Provider adapters (v0.4, ADR-008) are used
    # only when their API key is present; otherwise selection degrades to stub.
    llm_provider: Literal["stub", "heuristic", "openai", "anthropic", "gemini"] = "stub"
    openai_model: str = "gpt-4o-mini"
    anthropic_model: str = "claude-haiku-4-5-20251001"
    gemini_model: str = "gemini-2.5-flash"  # 1.5-flash was retired; flash-latest also valid

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

    # Ranker weights (P3.2). The retrieval score is a weighted blend of six [0,1]
    # signals. These defaults prioritize semantic + keyword relevance; they are the
    # starting point, not a magic constant — tune per deployment (env now, per-tenant
    # later). Weights are normalized to sum to 1 at load. See docs/architecture.md.
    ranker_weight_semantic: float = 0.35
    ranker_weight_keyword: float = 0.20
    ranker_weight_importance: float = 0.15
    ranker_weight_confidence: float = 0.10
    ranker_weight_recency: float = 0.10
    ranker_weight_reinforcement: float = 0.10
    ranker_score_floor: float = 0.05  # drop candidates below this blended score

    # Reliability knobs (used by core.reliability).
    llm_timeout_seconds: float = 8.0
    retrieval_timeout_seconds: float = 3.0
    circuit_breaker_threshold: int = 5
    circuit_breaker_reset_seconds: float = 30.0

    # ── derived helpers ──────────────────────────────────────────────────────
    def cors_origins_list(self) -> list[str]:
        """CORS allow-list as a list. '*' stays a single wildcard entry."""
        raw = self.cors_allow_origins.strip()
        if not raw or raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    def production_readiness_errors(self) -> list[str]:
        """Fail-closed startup checks for the production profile.

        Returns a list of human-readable violations. Empty means the current
        settings are safe to serve production traffic. This is intentionally
        conservative: every insecure *default* that is convenient for the demo is
        a hard error here, so a real deployment cannot silently inherit them.
        Only enforced when ``profile == "production"``; callers should no-op
        otherwise. See docs/production-readiness.md and invariants #1/#5.
        """
        if self.profile != "production":
            return []
        errors: list[str] = []
        if self.storage != "postgres":
            errors.append(
                f"storage={self.storage!r}: the in-memory store loses all data on "
                "restart and has no RLS — set MEMORYOPS_STORAGE=postgres."
            )
        if self.auth_mode == "none":
            errors.append(
                "auth_mode='none': every request would be trusted unauthenticated — "
                "set MEMORYOPS_AUTH_MODE=trusted_header|jwt."
            )
        if "*" in self.cors_origins_list():
            errors.append(
                "cors_allow_origins='*': any origin could call the API from a browser — "
                "set MEMORYOPS_CORS_ALLOW_ORIGINS to an explicit allow-list."
            )
        # Demo credentials shipped in the default database_url must never reach prod.
        if self.storage == "postgres" and (
            "memoryops:memoryops@" in self.database_url or "@localhost" in self.database_url
        ):
            errors.append(
                "database_url uses the bundled demo credentials / localhost — "
                "point MEMORYOPS_DATABASE_URL / DATABASE_URL at the real database."
            )
        if self.public_evals:
            errors.append(
                "public_evals=true: the eval trigger is a denial-of-wallet vector when "
                "public — set MEMORYOPS_PUBLIC_EVALS=false."
            )
        errors.extend(self._provider_readiness_errors())
        errors.extend(self._governance_readiness_errors())
        return errors

    def _governance_readiness_errors(self) -> list[str]:
        """Reject a production deployment with governance switched off.

        The research-ablation switches (`MEMORYOPS_GOVERNANCE_PROFILE=disabled`,
        `MEMORYOPS_ABLATE_*`) exist so the paper study can measure a governed system
        against a mechanism-matched ungoverned twin. They ship in the same binary as
        production, and nothing stopped them being combined with
        `MEMORYOPS_PROFILE=production`.

        Verified before this check existed: a fully hardened production config
        (postgres, jwt, explicit CORS, real DSN, evals off) plus
        `MEMORYOPS_GOVERNANCE_PROFILE=disabled` produced **no** readiness errors and
        stored a live API key with `status=active` — the policy broker's BLOCK never
        ran. Every one of the seven invariants could be disabled by an env var while
        the deployment reported itself production-ready.

        All seven flags default to enabled, so this rejects only deployments that
        explicitly turned governance off.

        This is the guard, not the cure. The stronger fix is architectural — ship the
        ablation wiring in a separate `memoryops-research` package or application
        factory so a production binary cannot express these states at all. Tracked
        separately; this closes the hole now.
        """
        import os

        errors: list[str] = []
        if self.governance_profile != "full":
            errors.append(
                f"governance_profile={self.governance_profile!r}: research ablation "
                "disables the policy broker, transactional evidence, tombstone "
                "propagation and the context gates — unset "
                "MEMORYOPS_GOVERNANCE_PROFILE for production."
            )
        for attr, env, what in (
            (
                "govern_policy_enforcement",
                "MEMORYOPS_ABLATE_POLICY_BROKER",
                "the policy broker would not run before storage (invariant #5): "
                "secrets and injection payloads would be stored active",
            ),
            (
                "govern_transactional_evidence",
                "MEMORYOPS_ABLATE_TRANSACTIONAL_EVIDENCE",
                "lifecycle mutations and their audit events would no longer commit "
                "atomically (invariant #7)",
            ),
            (
                "govern_tombstone_propagation",
                "MEMORYOPS_ABLATE_TOMBSTONE_PROPAGATION",
                "deletion would not propagate to derived memories (invariant #2)",
            ),
            (
                "admission_gate_enabled",
                "MEMORYOPS_ADMISSION_GATE",
                "no memory would be checked for admissibility before entering context",
            ),
            (
                "recall_gate_enabled",
                "MEMORYOPS_RECALL_GATE",
                "audience clearance would not be enforced on recall",
            ),
            (
                "output_gate_enabled",
                "MEMORYOPS_OUTPUT_GATE",
                "generated answers would not be checked for disclosure of blocked memory",
            ),
        ):
            if not getattr(self, attr):
                errors.append(f"{attr}=false: {what} — set {env} back on for production.")

        # An ABLATE_* variable set to *any* value flips its control off, so its mere
        # presence is disqualifying regardless of the value.
        present = sorted(k for k in os.environ if k.startswith("MEMORYOPS_ABLATE_"))
        if present:
            errors.append(
                f"research ablation variables set in a production environment: "
                f"{', '.join(present)} — these disable governance controls and must "
                "be unset."
            )
        return errors

    def _provider_readiness_errors(self) -> list[str]:
        """Fail-closed checks for provider selection (production profile only).

        Every provider adapter imports its SDK lazily and degrades to a stub/no-op
        when the SDK or key is missing, so the app always starts. That is right for
        dev and for tests (which must run offline), but in production it means an
        operator can set MEMORYOPS_LLM_PROVIDER=openai, see a healthy service, and
        be served deterministic stub output indefinitely with only a log line. A
        deployment that asked for a real provider must fail loudly instead.
        """
        from importlib.util import find_spec

        errors: list[str] = []

        def missing(module: str) -> bool:
            # find_spec only resolves the module; it does not import the SDK, so this
            # stays cheap and side-effect-free at startup.
            try:
                return find_spec(module) is None
            except (ImportError, ValueError):  # namespace/partial install
                return True

        # ── LLM provider ────────────────────────────────────────────────────
        llm_requirements = {
            "openai": ("openai", "openai", self.openai_api_key, "OPENAI_API_KEY"),
            "anthropic": ("anthropic", "anthropic", self.anthropic_api_key, "ANTHROPIC_API_KEY"),
            # Legacy SDK module — matches app/llm/gemini_provider.py's actual import.
            "gemini": ("google.generativeai", "gemini", self.gemini_api_key, "GEMINI_API_KEY"),
        }
        if self.llm_provider in llm_requirements:
            module, extra, key, key_env = llm_requirements[self.llm_provider]
            if not key:
                errors.append(
                    f"llm_provider={self.llm_provider!r} but {key_env} is unset: the provider "
                    "would silently degrade to the deterministic stub — set the key or "
                    "MEMORYOPS_LLM_PROVIDER=stub."
                )
            if missing(module):
                errors.append(
                    f"llm_provider={self.llm_provider!r} but the {module!r} SDK is not "
                    f"installed: the provider would silently degrade to the deterministic "
                    f"stub — install it (pip install 'memoryops-api[{extra}]')."
                )

        # ── Embedding provider ──────────────────────────────────────────────
        # Stricter than the LLM path: a wrong embedding does not just degrade one
        # answer, it persists a vector in the wrong space (see app/embeddings/providers.py).
        if self.embeddings_provider == "openai":
            if not self.openai_api_key:
                errors.append(
                    "embeddings_provider='openai' but OPENAI_API_KEY is unset: memories "
                    "would be embedded with the stub and stored in a different vector "
                    "space than the configured model — set the key or "
                    "MEMORYOPS_EMBEDDING_PROVIDER=stub."
                )
            if missing("openai"):
                errors.append(
                    "embeddings_provider='openai' but the 'openai' SDK is not installed: "
                    "memories would be embedded with the stub — install it "
                    "(pip install 'memoryops-api[openai]')."
                )

        # ── External vector backend (ADR-021) ───────────────────────────────
        vector_requirements = {
            "qdrant": ("qdrant_client", "qdrant"),
            "lancedb": ("lancedb", "lancedb"),
            "weaviate": ("weaviate", "weaviate"),
        }
        if self.vector_index in vector_requirements:
            module, extra = vector_requirements[self.vector_index]
            if missing(module):
                errors.append(
                    f"vector_index={self.vector_index!r} but the {module!r} client is not "
                    f"installed: the factory would fall back to the in-memory index, which "
                    f"loses all vectors on restart — install it "
                    f"(pip install 'memoryops-api[{extra}]')."
                )
        return errors


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
    for env_name, field_name in (
        ("MEMORYOPS_RANK_W_SEMANTIC", "ranker_weight_semantic"),
        ("MEMORYOPS_RANK_W_KEYWORD", "ranker_weight_keyword"),
        ("MEMORYOPS_RANK_W_IMPORTANCE", "ranker_weight_importance"),
        ("MEMORYOPS_RANK_W_CONFIDENCE", "ranker_weight_confidence"),
        ("MEMORYOPS_RANK_W_RECENCY", "ranker_weight_recency"),
        ("MEMORYOPS_RANK_W_REINFORCEMENT", "ranker_weight_reinforcement"),
        ("MEMORYOPS_RANK_SCORE_FLOOR", "ranker_score_floor"),
    ):
        if (val := os.getenv(env_name)) is not None:
            with contextlib.suppress(ValueError):
                overrides[field_name] = float(val)
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
    # Governance profile (paper study apparatus). MEMORYOPS_GOVERNANCE_PROFILE=disabled
    # produces the ungoverned twin S0-U; "full" (default) is the frozen behavior. The
    # profile sets the per-control defaults; an individual MEMORYOPS_ABLATE_* env var
    # then overrides exactly one control (Experiment C). A control is *off* when the
    # profile is disabled OR its ablation flag is set.
    profile_disabled = os.getenv("MEMORYOPS_GOVERNANCE_PROFILE") == "disabled"
    if os.getenv("MEMORYOPS_GOVERNANCE_PROFILE") in ("full", "disabled"):
        overrides["governance_profile"] = os.getenv("MEMORYOPS_GOVERNANCE_PROFILE")

    def _ablated(control_env: str) -> bool:
        v = os.getenv(control_env)
        return profile_disabled or (v is not None and v.lower() not in ("0", "false", "no"))

    if profile_disabled or os.getenv("MEMORYOPS_ABLATE_POLICY_BROKER") is not None:
        overrides["govern_policy_enforcement"] = not _ablated("MEMORYOPS_ABLATE_POLICY_BROKER")
    if profile_disabled or os.getenv("MEMORYOPS_ABLATE_TRANSACTIONAL_EVIDENCE") is not None:
        overrides["govern_transactional_evidence"] = not _ablated(
            "MEMORYOPS_ABLATE_TRANSACTIONAL_EVIDENCE"
        )
    if profile_disabled or os.getenv("MEMORYOPS_ABLATE_TOMBSTONE_PROPAGATION") is not None:
        overrides["govern_tombstone_propagation"] = not _ablated(
            "MEMORYOPS_ABLATE_TOMBSTONE_PROPAGATION"
        )
    # The disabled profile also turns the context gates off (unless an env var already
    # set them). Individual gate toggles remain the per-control ablation knobs.
    if profile_disabled:
        for env_name, field_name in (
            ("MEMORYOPS_ADMISSION_GATE", "admission_gate_enabled"),
            ("MEMORYOPS_RECALL_GATE", "recall_gate_enabled"),
            ("MEMORYOPS_OUTPUT_GATE", "output_gate_enabled"),
        ):
            if os.getenv(env_name) is None:
                overrides[field_name] = False

    if (val := os.getenv("MEMORYOPS_STORAGE")) in ("memory", "postgres"):
        overrides["storage"] = val
    # v2.3 deployment profile + CORS allow-list. Public operator knobs.
    if (val := os.getenv("MEMORYOPS_PROFILE")) in ("dev", "production"):
        overrides["profile"] = val
    if (val := os.getenv("MEMORYOPS_CORS_ALLOW_ORIGINS")) is not None:
        overrides["cors_allow_origins"] = val
    # Honor the conventional DATABASE_URL (Railway/Heroku-style) if MEMORYOPS_* unset.
    if (val := os.getenv("MEMORYOPS_DATABASE_URL") or os.getenv("DATABASE_URL")):
        overrides["database_url"] = val
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
