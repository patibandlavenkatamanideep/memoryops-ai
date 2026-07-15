# Launch Post

AI assistants remember information, but most cannot explain why it was stored,
where it was used, or whether deletion actually worked.

MemoryOps is an open-source governed memory runtime that makes that lifecycle
visible:

1. Capture a preference through the policy broker.
2. Retrieve it only when tenant, user, relevance, and audience checks pass.
3. Show the memory usage trace for the answer.
4. Delete or govern the memory, then prove it no longer appears in retrieval.
5. Inspect the audit trail that recorded each step.

Try the lifecycle in the playground, install the SDK from PyPI, and reproduce the
governance benchmark locally:

- Playground: https://memoryops-ai-production.up.railway.app
- PyPI: https://pypi.org/project/memoryops-sdk/
- Benchmark: https://github.com/patibandlavenkatamanideep/memoryops-ai/blob/main/benchmark/SCORECARD.md
- Repository: https://github.com/patibandlavenkatamanideep/memoryops-ai

Next after launch: live-provider and live-adapter validation, starting with the
provider extraction harness and vector backend adapters.
