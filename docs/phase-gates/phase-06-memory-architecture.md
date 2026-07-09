# Phase 6 — Memory Architecture

**Question:** Short-term vs long-term, RAG, hybrid retrieval.

## MemoryOps mapping
Typed memory (episodic, semantic, procedural, preference, project, constraint,
workflow, knowledge, system). Long-term memory in Postgres + pgvector; working/
session memory is simplified in v0.1–v0.2. Hybrid retrieval = vector cosine +
keyword overlap, blended by the ranker.

## Gate (must be true to pass)
- Memory types are enumerated and treated differently.
- Retrieval is hybrid and tenant/user/status-filtered.
- Deleted and pending memories are never retrievable.
- Embedding generation degrades gracefully (stub fallback; keyword-only on failure).
- Retrieval results carry an explainable `score_breakdown` and a `retrieval_mode`.
- A memory enters context only if it is relevant **and** allowed: the Context
  Admission Gate runs after rank / before compose and each answer carries an
  explainable Memory Usage Trace (v1.3).
- The deletion guarantee propagates to *derived* artifacts: tombstone lineage +
  `BLOCK_TOMBSTONED_ANCESTOR` block anything derived from a deleted ancestor, proven
  by `leakage` / `derived_tombstone` evals (v1.4).

## Evidence
- `services/api/app/embeddings/` (provider interface + stub + OpenAI)
- `services/api/app/db/repository.py::search_candidates` (pgvector + in-memory)
- `services/api/app/services/{retriever,ranker,admission_gate,context_composer}.py`, `services/api/app/db/lineage.py`
- `services/api/tests/{test_retrieval,test_hybrid_retrieval,test_pgvector_retrieval,test_retrieval_degradation,test_embeddings,test_admission_gate,test_memory_usage_trace,test_deletion_proof_lineage}.py`
- [ADR-002 retrieval](../../infra/adr/ADR-002-retrieval.md), [ADR-006 pgvector/RLS](../../infra/adr/ADR-006-pgvector-rls-retrieval.md), [ADR-017 admission gate + usage trace](../../infra/adr/ADR-017-context-admission-gate.md), [ADR-018 tombstone lineage](../../infra/adr/ADR-018-tombstone-lineage-deletion-proof.md)

## Gaps to close (→ v0.4+)
- Working/session memory tier in Redis.
- Learned reranker; provider extraction/evaluation (v0.4).

## Status: ✅ Implemented (v0.3 — provider embeddings, pgvector retrieval, hybrid + score breakdown)
