# Validating the Qdrant adapter against a live server

The Qdrant vector-index adapter is **contract-tested** — it conforms to
`assert_vector_index_contract`, but a live Qdrant server isn't a CI dependency. This
guide runs the same governance contract against a real Qdrant so you can certify it in
your environment. The pattern generalizes to LanceDB and Weaviate.

## 1. Run Qdrant locally

```bash
docker run -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

## 2. Install the client + create the collection

```bash
pip install qdrant-client
python - <<'PY'
from qdrant_client import QdrantClient, models
c = QdrantClient(url="http://localhost:6333")
c.recreate_collection(
    collection_name="memoryops",
    vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE),
)
print("collection ready")
PY
```

> Use the embedding dimension your provider emits (the stub is small; OpenAI is 1536).
> The contract test below uses size-3 vectors.

## 3. Run the governance contract against live Qdrant

```bash
python - <<'PY'
import sys; sys.path.insert(0, "services/api")
sys.path.insert(0, "services/api/tests")
from app.db.vector.qdrant_index import QdrantVectorIndex
from test_vector_index import assert_vector_index_contract   # reuse the CI contract

idx = QdrantVectorIndex(url="http://localhost:6333", collection="memoryops")
assert idx.available(), "Qdrant not reachable"
assert_vector_index_contract(idx)
print("PASS — Qdrant upholds tenant isolation, deletion, and ranking")
PY
```

A pass proves the live adapter honors the same guarantees as the in-memory reference:
`query` only returns a scope's own vectors (isolation), a deleted id never comes back
(deletion), and closer vectors rank higher.

## 4. Point MemoryOps at it end-to-end

```bash
export MEMORYOPS_VECTOR_INDEX=qdrant
export MEMORYOPS_VECTOR_INDEX_URL=http://localhost:6333
export MEMORYOPS_VECTOR_INDEX_COLLECTION=memoryops
cd services/api && uvicorn app.main:app
```

Chat, then delete a memory and confirm it never returns — the same
`test_tenant_isolation.py` / `test_deletion.py` assertions hold, now backed by Qdrant.

## Making it a CI job (optional)

Add an opt-in job that runs Qdrant as a service container and executes step 3:

```yaml
  qdrant-live:
    runs-on: ubuntu-latest
    services:
      qdrant:
        image: qdrant/qdrant
        ports: ["6333:6333"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r services/api/requirements.txt qdrant-client pytest
      - run: python docs/adapters/_qdrant_contract_check.py   # steps 2–3 as a script
```

Gate it behind a label or `workflow_dispatch` so it doesn't slow every PR.
