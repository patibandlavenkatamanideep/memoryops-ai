# External memory-system comparison

## Purpose

Run the repository's existing deterministic governance probes through MemoryOps *and*
external memory systems, scored identically, so MemoryOps' behaviour can be compared
against something other than itself.

The benchmark is not designed for MemoryOps to win. Cases were fixed before the
external systems were added and were not changed afterwards. The measured outcome
below is reported as observed, including where it is unflattering.

## Systems

| Id | System | Configuration |
|----|--------|---------------|
| `S0` | MemoryOps, governed | full policy / retrieval / deletion path |
| `S0-U` | MemoryOps, governance disabled | ablation twin |
| `S1` | Full-context baseline | keeps raw history, no addressable memory |
| `S2` | Plain vector baseline | embed → cosine top-k → compose |
| `S3` | Rolling-summary baseline | single growing summary string |
| `S4` | **Mem0** | `mem0ai==2.0.17`, real product API |

### S4 (Mem0) configuration

| Setting | Value |
|---|---|
| `mem0ai` | `2.0.17` |
| `langchain` | `1.3.14` |
| `langchain-core` | `1.5.3` |
| Vector backend | local Qdrant, temporary directory, on-disk, no network |
| Embedder | the repository's deterministic embedder — **the same one `S2` uses** |
| LLM | `NeverCalledChatModel` — raises if invoked |
| Ingestion | `infer=False` |
| **Live provider calls** | **0** |

The embedder is held constant across `S2` and `S4` on purpose: the intent is to compare
*memory-system semantics*, not which embedding model is stronger.

Mem0 defaults to OpenAI for both its LLM and its embedder, and constructs the LLM
eagerly in `Memory.__init__` — so `infer=False` alone does not avoid a provider. Both
model objects are injected through Mem0's sanctioned `langchain` provider. The chat
model raises on invocation, which is what makes "0 provider calls" a checked property
rather than an assertion.

## Result semantics

Four-valued, per `paper/protocol.md` §5:

| Outcome | Meaning |
|---|---|
| `PASS` | supported capability, requirement met |
| `FAIL` | supported capability, requirement violated |
| `UNSUPPORTED` | the system has no such capability — a finding, never a failure |
| `ERROR` | crash, timeout, or malformed integration result |

`UNSUPPORTED` never enters the correctness denominator. `ERROR` stays visible.

- **Coverage** = `(PASS + FAIL) / total cases`
- **Conditional correctness** = `PASS / (PASS + FAIL)`

## Cases

Four deterministic invariant cases, scored from *retrieved memory* rather than model
prose, so they are meaningful under a deterministic stub:

| Suite | Case | Requirement |
|---|---|---|
| `tenant_isolation` | `iso-cross-tenant` | tenant B must not recall tenant A's fact |
| `tenant_isolation` | `iso-cross-user` | user C must not recall user A's fact |
| `deletion_leakage` | `del-exact-probe` | a deleted memory must not resurface on an exact probe |
| `deletion_leakage` | `del-paraphrased-probe` | …nor on a paraphrased probe |

## Raw results

| System | Pass | Fail | Unsupported | Error | Coverage | Conditional correctness |
|--------|-----:|-----:|------------:|------:|---------:|------------------------:|
| S0 MemoryOps (governed) | 4 | 0 | 0 | 0 | 4/4 (100%) | 4/4 (100%) |
| S0-U MemoryOps (ungoverned) | 4 | 0 | 0 | 0 | 4/4 (100%) | 4/4 (100%) |
| S1 full-context | 2 | 0 | 2 | 0 | 2/4 (50%) | 2/2 (100%) |
| S2 plain vector | 4 | 0 | 0 | 0 | 4/4 (100%) | 4/4 (100%) |
| S3 rolling summary | 2 | 0 | 2 | 0 | 2/4 (50%) | 2/2 (100%) |
| **S4 Mem0** | **4** | **0** | **0** | **0** | **4/4 (100%)** | **4/4 (100%)** |

`S1` and `S3` are `UNSUPPORTED` on both deletion cases because neither has addressable
memory to delete. That is a capability finding, not a failure.

## What this shows

**On the four current deterministic deletion/isolation probes, the plain vector
baseline also passes all cases. These probes therefore do not, by themselves,
demonstrate a governance advantage for MemoryOps.**

Mem0 likewise passes all four. So do MemoryOps with governance enabled *and* with
governance disabled (`S0-U`).

The honest reading: at this probe resolution, four systems are tied. A simple
embed-and-retrieve store scoped by key is sufficient to pass these particular cases,
and nothing here distinguishes a governed memory layer from an ungoverned one.

## Limitations

1. **Only the current protocol cases were run.** Four deterministic invariant cases,
   two suites. No case was added or altered after seeing results.

2. **Mem0 runs with `infer=False`.** Ingestion stores the supplied fact verbatim.

3. **Mem0's LLM-driven behaviour is therefore not evaluated** — extraction,
   consolidation, deduction and memory rewriting are exactly the parts an LLM drives,
   and all are out of scope here. Nothing in this document speaks to Mem0's product
   quality.

4. **A `PASS` for isolation does not imply an equivalent enforcement mechanism.**
   MemoryOps enforces tenant isolation in the application *and* at the database via
   Postgres `FORCE ROW LEVEL SECURITY`, verified separately by a fail-closed
   behavioural probe. Mem0 is scoped here through its identity/filter semantics, with
   the harness `Scope(tenant, user)` mapped to a compound `user_id` because Mem0 has no
   tenant construct. The benchmark scores the externally observed requirement, not
   architectural equivalence — these are different guarantees that happen to produce
   the same observable outcome on these probes.

5. **`S2` passing every current probe means these probes are insufficient to establish
   overall governance superiority.** Capabilities the protocol defines but these cases
   do not exercise — policy-before-storage, consent, retention, admission and output
   gates, audit evidence, deletion lineage — remain unmeasured here. They are existing
   protocol scope, not a response to this result, and were deliberately not added to
   this run.

6. **No paid LLM or provider calls were made.** 0 live calls across every system.

## Reproduce

The benchmark extra is optional and quarantined from every runtime image. Without it,
`S4` is simply absent and the remaining five systems still run.

```bash
cd services/api && pip install -r requirements-dev.txt -r requirements-benchmark.txt
cd ../.. && PYTHONPATH=".:services/api" MEMORYOPS_STORAGE=memory \
  python paper/run_experiments.py
```

Adapter tests:

```bash
PYTHONPATH=".:services/api" python -m pytest paper/harness/tests/test_mem0_adapter.py
```

No provider credentials are required or used. Results were identical across two
consecutive full runs.
