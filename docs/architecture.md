# Architecture — MemoryOps AI

MemoryOps AI is a **governed memory lifecycle system**. It treats memory not as a vector store but
as state that must be captured, evaluated, stored, retrieved, ranked, composed, updated, forgotten,
and audited — under five cross-cutting planes.

```text
                         ┌──────────────────────────────────────────────┐
                         │  PLANES: Security · Governance · Observability │
                         │          Reliability · Evaluation             │
                         └──────────────────────────────────────────────┘

 USER / GATEWAY
     │
     ├──────────────── WRITE PATH ─────────────────────────────────────────────┐
     │                                                                          │
     │  message ─▶ Extractor ─▶ Policy Broker ─▶ Write Service ─▶ Memory Store  │
     │              (candidates)   (decision)     (dedup/embed)    (typed)      │
     │                                  │                              │        │
     │                                  └────────────▶ Audit Log ◀─────┘        │
     │                                                                          │
     ├──────────────── READ PATH ──────────────────────────────────────────────┤
     │                                                                          │
     │  message ─▶ Retriever ─▶ Ranker ─▶ Context Composer ─▶ Response LLM      │
     │             (hybrid)      (score)    (compact block)     (answer)        │
     │                                                                          │
     └──────────────── BACKGROUND ─────────────────────────────────────────────┘
        Decay · Reflection · Conflict Resolution · Compression
```

## Diagrams

### System architecture

```mermaid
flowchart TB
    subgraph Client["apps/web — Next.js"]
        UI["Chat · Memory Dashboard · Admin · Architecture"]
    end

    subgraph API["services/api — FastAPI"]
        GW["Gateway<br/>tenant/user · settings · temporary-chat guard"]

        subgraph WRITE["Write path"]
            EX["Extractor"]
            PB["Policy Broker<br/>secrets · PII · injection · dedup"]
            WS["Write Service<br/>embed · provenance"]
        end

        subgraph READ["Read path"]
            RT["Retriever (hybrid)"]
            RK["Ranker"]
            CC["Context Composer"]
        end

        AUD["Audit Service<br/>append-only"]
        REPO["Repository<br/>tenant-scoped · excludes deleted"]
    end

    subgraph CORE["core (cross-cutting)"]
        CFG["config"]
        LOG["redacting JSON logging + trace_id"]
        REL["reliability: timeout/retry/breaker"]
    end

    subgraph DATA["Data"]
        PG[("Postgres + pgvector")]
        RD[("Redis")]
        MEM[["in-memory backend (dev/tests)"]]
    end

    subgraph WORKER["services/worker"]
        JOBS["decay · archive · conflict · reflection"]
    end

    UI -->|"/api/chat, /api/memories, /api/audit"| GW
    GW --> EX --> PB --> WS --> REPO
    GW --> RT --> RK --> CC --> GW
    WS --> AUD
    GW --> AUD
    RT --> REPO
    AUD --> REPO
    REPO --> PG
    REPO --> MEM
    GW -. session cache .-> RD
    WORKER --> REPO
    API -.uses.- CORE

    classDef plane fill:#0b1f3a,stroke:#5b8cff,color:#cfe0ff;
    class CORE plane;
```

### Memory lifecycle (state machine)

```mermaid
stateDiagram-v2
    [*] --> candidate: Extractor
    candidate --> blocked: BLOCK (secret/injection)
    candidate --> dropped: DROP_LOW_UTILITY
    candidate --> pending: PENDING_APPROVAL
    candidate --> active: SAVE
    candidate --> active: UPDATE / MERGE (reinforce)

    pending --> active: approve
    pending --> rejected: reject
    active --> archived: decay / archive
    active --> deleted: delete (forget)

    deleted --> [*]: never retrievable again
    blocked --> [*]: not stored (audit only)
    dropped --> [*]: not stored (audit only)
```

### Chat request sequence

```mermaid
sequenceDiagram
    actor U as User
    participant GW as Gateway
    participant R as Retriever+Ranker
    participant P as Policy Broker
    participant W as Write Service
    participant A as Audit
    participant DB as Repository

    U->>GW: POST /api/chat
    alt temporary_chat or memory disabled
        GW->>A: temporary_chat_skipped
        GW-->>U: answer (no read, no write)
    else normal turn
        GW->>R: retrieve + rank (safe_call)
        R->>DB: active, tenant-scoped memories
        R-->>GW: ranked used_memories
        GW->>A: memory_retrieved
        GW->>P: evaluate candidate(s)
        P-->>GW: decision
        GW->>W: commit(decision)
        W->>DB: write (SAVE/PENDING) or none (BLOCK/DROP)
        W->>A: memory_created / blocked / ...
        GW-->>U: answer + used_memories + candidate decisions
    end
```

## Write path (Phase 1 — implemented)

1. **Gateway** ([services/api/app/services/gateway.py](../services/api/app/services/gateway.py))
   - Attaches `tenant_id` / `user_id`, loads `memory_settings`.
   - If `temporary_chat` is on or memory is disabled → **no read, no write** (invariant #6).
   - Orchestrates extractor → policy broker → write service and returns memory metadata.

2. **Extractor** ([extractor.py](../services/api/app/services/extractor.py))
   - Turns a conversation turn into zero or more candidate memories (JSON).
   - Classifies `memory_type`, assigns `confidence` + `importance`, preserves `source_excerpt`.
   - Heuristic by default (no API key needed); pluggable LLM adapter via `app/core/llm.py`.

3. **Policy Broker / Evaluator** ([policy_broker.py](../services/api/app/services/policy_broker.py))
   - Runs **before storage** (invariant #5).
   - Secret/PII detection (API keys, tokens, credentials) → `BLOCK`.
   - Sensitivity classification; sensitive + `require_approval_for_sensitive` → `PENDING_APPROVAL`.
   - Low-utility/duplicate → `DROP_LOW_UTILITY`; near-duplicate of existing → `UPDATE_EXISTING` /
     `MERGE_WITH_EXISTING`; otherwise `SAVE`.

4. **Write Service** ([write_service.py](../services/api/app/services/write_service.py))
   - Deduplicates, generates embedding (heuristic or provider), writes to the typed store with full
     provenance (invariant #3), appends an audit event (invariant #7).

5. **Memory Store** ([db/](../services/api/app/db/))
   - Repository abstraction. `memory` (in-process, for tests/demo) or `postgres` (pgvector).
   - All queries are tenant + user scoped (invariant #1) and exclude `deleted` (invariant #2).

6. **Audit Log** ([audit.py](../services/api/app/services/audit.py))
   - Append-only events for every lifecycle action.

## Read path (Phase 2 — scaffolded)

- **Retriever** — hybrid: vector similarity + keyword + (future) graph. Filters by
  tenant/user/status/sensitivity. Deleted + pending memories are excluded.
- **Ranker** — `0.35·semantic + 0.20·keyword + 0.15·importance + 0.10·recency + 0.10·confidence +
  0.10·reinforcement`.
- **Context Composer** — compact context block with internal source IDs; never leaks hidden memory.
- **Context Compression (v0.2.1, optional)** — after composition and before the LLM, the
  composed *governed* context block may be compressed by an optional `ContextCompressor`
  (`MEMORYOPS_CONTEXT_COMPRESSION=headroom`). Default is a transparent no-op. It never runs
  before the policy broker and never touches the raw user message; failure degrades to the
  uncompressed block. See [ADR-007](../infra/adr/ADR-007-headroom-token-compression.md).
- **Graceful degradation** — retrieval failure is caught and the assistant still answers (#4).

## Background path (Phase 5 — scaffolded)

`services/worker` hosts decay (age out weights), reflection/compression (collapse repeats),
conflict resolution (reconcile contradictions), and system-learning memory generation.

## Typed memory model (invariant #9)

| Type        | Meaning                                   | Example                                  |
|-------------|-------------------------------------------|------------------------------------------|
| episodic    | a specific event/turn                     | "Asked about pgvector on 2026-06-20"     |
| semantic    | a stable fact about the user/world        | "Works at an enterprise SaaS company"    |
| procedural  | how the user wants things done            | "Prefers enterprise-style explanations"  |
| preference  | a like/dislike                            | "Dislikes emojis in answers"             |
| project     | scoped to ongoing work                    | "Building MemoryOps AI for a hackathon"  |
| constraint  | a hard rule                               | "Never store my home address"            |
| workflow    | a repeated multi-step process             | "Reviews PRs before merge"               |
| knowledge   | document/RAG-derived fact                 | "Spec X says retention is 90 days"       |
| system      | reflections / eval learnings              | "Golden case #3 regressed"               |

## Where invariants live

| # | Invariant            | Enforced in                                                        |
|---|----------------------|-------------------------------------------------------------------|
| 1 | Tenant isolation     | repository tenant-scoped queries; tested in `tests/test_tenant_isolation.py` |
| 2 | Deletion guarantee   | repository filters `status != deleted`; `tests/test_deletion.py`  |
| 3 | Provenance           | `source` NOT NULL; write service always sets it                   |
| 4 | Graceful degradation | gateway try/except around retrieval                               |
| 5 | Policy-before-storage| gateway calls policy broker before write service                  |
| 6 | Temporary chat       | gateway short-circuit; `tests/test_temporary_chat.py`             |
| 7 | Auditability         | every service action calls `AuditService.record`                  |

## Failure modes considered

- LLM/extractor unavailable → heuristic extractor still produces candidates.
- Embeddings provider down → deterministic heuristic embedding.
- DB down for reads → retrieval degrades, response still generated.
- Policy false-negative → defense in depth: secret regex + sensitivity classifier + approvals.
