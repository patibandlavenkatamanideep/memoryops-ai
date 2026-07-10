# Adapter compatibility

MemoryOps is deliberately honest about what is exercised where. Three support levels:

- **Fully tested locally** — runs in CI against the real stack every push.
- **Contract-tested** — the adapter conforms to a written contract
  (`assert_vector_index_contract`), but a live external service is **not** a CI
  dependency. Correctness against a live server is validated by running the contract
  suite yourself (guides below).
- **Example integration** — import-guarded illustrative glue; not live-service tested
  in CI.

## Vector backends

Selected with `MEMORYOPS_VECTOR_INDEX` (see [storage-backends.md](../storage-backends.md)).
Every backend must pass the same governance contract — tenant isolation, deletion
non-reappearance, no-bypass, graceful degradation
(`services/api/tests/test_vector_index.py::assert_vector_index_contract`).

| Backend | `MEMORYOPS_VECTOR_INDEX` | Support level | Pip extra | Key env |
| --- | --- | --- | --- | --- |
| Postgres + pgvector | (via `MEMORYOPS_STORAGE=postgres`) | **fully tested locally** | `sqlalchemy`, `pgvector` | `DATABASE_URL` |
| In-memory | `memory` (default) | **fully tested locally** | none | — |
| Qdrant | `qdrant` | contract-tested | `qdrant-client` | `MEMORYOPS_VECTOR_INDEX_URL`, `..._API_KEY`, `..._COLLECTION` |
| LanceDB | `lancedb` | contract-tested | `lancedb` | `MEMORYOPS_VECTOR_INDEX_URI` |
| Weaviate | `weaviate` | contract-tested | `weaviate-client` (v4) | `MEMORYOPS_VECTOR_INDEX_URL`, `..._API_KEY` |
| Pinecone | — | **planned** (same shape: namespaced upsert/query + metadata filter) | `pinecone-client` | — |

If a selected backend can't be reached at startup, MemoryOps logs and falls back to the
in-memory index — retrieval quality degrades, governance does not.

**Validate a contract-tested backend against a live server:**
[qdrant-live-test.md](qdrant-live-test.md) (the pattern generalizes to LanceDB/Weaviate).

## Identity providers (v1.6)

Selected with `MEMORYOPS_AUTH_MODE` (see [auth-adapters.md](../auth-adapters.md)).

| Provider | Mode | Support level | Notes |
| --- | --- | --- | --- |
| Trusted upstream header | `trusted_header` | **fully tested locally** | BYO-auth; a proxy injects tenant/user |
| JWT (HS256/384/512) | `jwt` | **fully tested locally** | stdlib verification, no extra deps |
| JWT (RS256/384/512) | `jwt` | contract-tested | needs `cryptography`; PEM public key |
| Clerk / Auth0 / Supabase | `jwt` | claim-mapping recipes | same `jwt` mode, different claims/issuer |

## Agent frameworks (v2.1)

Example integrations wrapping `memoryops.GovernedMemory` — import-guarded, not
live-service tested in CI. See [agent-integrations.md](../agent-integrations.md).

| Framework | File | Support level |
| --- | --- | --- |
| LangGraph | `examples/integrations/langgraph_memory.py` | example integration |
| LlamaIndex | `examples/integrations/llamaindex_memory.py` | example integration |
| CrewAI | `examples/integrations/crewai_memory.py` | example integration |
| AutoGen | `examples/integrations/autogen_memory.py` | example integration |
| Semantic Kernel | `examples/integrations/semantic_kernel_memory.py` | example integration |
| OpenAI Agents SDK | `examples/integrations/openai_agents_memory.py` | example integration |

The `GovernedMemory` adapter itself **is** tested against the real in-process app
(`packages/memoryops-sdk/tests/test_integrations.py`) — only the per-framework wiring is
example-grade.

## Why this honesty

Contract-tested means the *governance* is proven (the contract is the thing that must
never break); it does not mean every network path against a live server runs in CI.
Being explicit about the difference is the point — it's easier to trust a matrix that
admits its edges.
