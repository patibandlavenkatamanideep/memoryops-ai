# Research Protocol — Governed Memory Runtime

> **Pre-registration.** This protocol is written **before** the final experiments are
> run. Questions, hypotheses, metrics, and decision rules below are fixed *now* so
> results cannot be reverse-engineered into a favorable story. Any change after the
> first result is produced is recorded in §12 (Deviations), with date and rationale.

## 0. Frozen experimental subject

| | |
|---|---|
| System under study | MemoryOps AI — governed memory runtime |
| Frozen at | git tag **`paper-v0.1-governance-runtime`** |
| Commit SHA | `54deeefa2f6776a429ae64750c268af8fd8d0e38` |
| Benchmark-facing API | frozen at this commit for the duration of the study |

Runtime-hardening, SDK, and UI work are **not** merged onto the baseline unless a
mechanism becomes an explicit experiment (see §7C). The subject is a fixed artifact,
not a moving product.

## 1. Research questions

- **RQ1 (correctness).** Does a governance layer reduce memory-lifecycle violations
  (deletion leakage, cross-tenant/user leakage, temporary-chat leakage, retention/
  consent non-compliance, policy-admission bypass) relative to ungoverned memory
  systems?
- **RQ2 (utility).** What is the cost to retrieval and answer quality of imposing
  those controls?
- **RQ3 (evidence integrity).** Does the system keep state and audit evidence
  consistent under injected failures and concurrent mutation?
- **RQ4 (overhead).** What latency, token, cost, and storage overhead does governance
  add, and how large is it relative to provider-generation latency?

## 2. Hypotheses & pre-registered decision rules

Each hypothesis has a **prediction**, a **primary metric**, and a **decision rule**
fixed before results. Where a numeric threshold would be arbitrary, the result is
reported **descriptively** with a 95% confidence interval (CI) and no pass/fail label.

### H1 — Governance correctness
- **Prediction.** MemoryOps has a strictly lower lifecycle-violation rate than every
  ungoverned baseline, and **zero** violations on the two *critical* invariant
  families (deletion & leakage; tenant/user isolation).
- **Primary metric.** Violation rate = violating cases / applicable cases, per family.
- **Decision rule (pre-registered).** H1 is **supported** iff (a) MemoryOps critical-
  family violation rate = 0, **and** (b) MemoryOps aggregate violation rate < that of
  each ungoverned baseline (non-overlapping 95% CIs). Otherwise reported descriptively.

### H2 — Utility preservation
- **Prediction.** Governance preserves most of the retrieval/answer quality of an
  equivalent ungoverned retrieval system.
- **Primary metric.** Answer correctness on the utility suite (§6, H2); secondary:
  retrieval precision/recall.
- **Decision rule (pre-registered, non-inferiority).** H2 is **supported** iff
  MemoryOps answer correctness is non-inferior to the strongest ungoverned retrieval
  baseline within a margin **Δ = 0.05 (absolute)** — i.e. `mo_correct ≥ best_baseline_correct − 0.05`
  with the CI respecting the margin. Δ is fixed now and revisable **only** before any
  utility result is generated. Retrieval metrics reported descriptively.

### H3 — Evidence integrity
- **Prediction.** Every mutation and its audit evidence stay consistent under partial
  failure and concurrency (the transactional-evidence guarantee, invariant #7).
- **Primary metric.** State–audit consistency rate under injected-failure and
  concurrency scenarios (§7D).
- **Decision rule (pre-registered).** H3 is **supported** iff consistency = 100%
  (zero half-applied mutations, zero orphan/duplicate audit rows, one continuous
  audit chain). This is binary by design; any single inconsistency refutes H3.

### H4 — Operational overhead
- **Prediction.** Governance adds measurable latency/storage overhead but remains a
  small fraction of provider-generation latency.
- **Primary metric.** Governance-attributable overhead: `latency(MemoryOps) −
  latency(plain-vector baseline)`, plus tokens, cost, and DB/audit growth.
- **Decision rule (descriptive + directional).** Reported descriptively (p50/p95/p99
  with CIs). The directional claim tested: governance-attributable **p50** overhead is
  **less than** provider-generation p50 (governance is not the dominant cost). No
  arbitrary absolute threshold.

## 3. Systems under test

All systems are driven through one neutral `MemorySystemAdapter` (Phase 2) so each
receives identical inputs and is scored by the identical rubric.

| # | System | Governance | Role |
|---|--------|-----------|------|
| S0 | MemoryOps (governed) @ baseline tag | full | subject |
| S1 | Full-context (all history to the model) | none | ungoverned ceiling on recall |
| S2 | Plain vector memory (embed → top-k → compose) | none | standard RAG memory |
| S3 | Summary memory (rolling conversation summary) | none | compression baseline |
| S4 | Mem0 | partial (product-defined) | external memory system |
| S5 *(optional)* | Zep/Graphiti or other structured memory | partial | second external system |

Four controlled baselines (S1–S4) are the primary comparison; S5 is optional. Fewer,
correctly-controlled baselines beat many partially-working integrations.

## 4. Held-constant controls

To prevent "the model/prompt caused it" objections, every system shares:

- **LLM** (single fixed model id + version), **temperature**, **max output length**;
- **embedding model** (single fixed id) where the system embeds;
- **prompt template** for answer composition, identical where the system's interface
  allows it (deviations recorded per system in §12);
- **query set**, **scope** (tenant/user), **conversation history**, and **mutation
  sequence** per case;
- **hardware**, **Postgres + pgvector configuration**, and **random seed(s)**.

Exact pinned values (model id, embedding id, temperature, seeds, hardware) are
recorded in `paper/configs/main.yaml` and stamped into every result file (§6, Phase 6).

## 5. Evaluation model

Each case yields exactly one outcome:

- **pass** — required behavior observed;
- **fail** — required behavior violated;
- **unsupported** — the system has no capability for the operation (e.g. no deletion,
  no audit export). Reported **separately** — lack of a governance capability is a
  finding, not a normal failure, and is never silently counted as `fail`;
- **error** — crash/timeout/malformed output.

**Model-independent invariant cases** (deletion, isolation, retention, consent,
admission — deterministic) are kept **separate** from **model-dependent quality
cases** (recall/answer correctness). Invariant cases run once (deterministic); quality
cases run over N seeds (§9).

## 6. Metrics

**H1 — governance (Experiment A).** violation rate; deletion-leakage rate;
cross-tenant/user-leakage rate; temporary-chat-leakage rate; policy-admission-bypass
rate; consent/retention-compliance rate; provenance-availability rate;
audit/evidence-availability rate; unsupported-operation rate.

**H2 — utility (Experiment B).** retrieval precision; retrieval recall; answer
correctness; temporal-update correctness; contradiction resolution; multi-hop recall;
selective-forgetting accuracy.

**H3 — integrity (Experiment D).** state–audit consistency rate; audit-chain
continuity; duplicate/orphan-evidence count.

**H4 — overhead (Experiment D).** p50/p95/p99 latency **broken out by stage**
(ingest / retrieve / generate), throughput, provider-call count, input/output tokens,
estimated cost, database growth, audit-event growth, failure-recovery status.

## 7. Experiment families

- **A — Governance comparison → H1.** All systems, full benchmark; the central
  results table is the per-system violation/leakage/compliance/availability matrix.
- **B — Memory utility → H2.** All systems, utility suite; precision/recall/answer
  correctness and the temporal/multi-hop/forgetting metrics.
- **C — Ablations → attribution (not a hypothesis test).** MemoryOps with individual
  controls disabled **in isolated experiment configuration only** (never a production
  deployment): no policy broker; no admission gate; no output gate; no tombstone
  propagation; no hybrid retrieval; no conflict detection; no transactional evidence.
  Attributes each result to a mechanism.
- **D — Reliability & systems performance → H3, H4.** Injected scenarios: failure
  after mutation before audit; failure after audit insert before commit; concurrent
  audit appends; worker failure mid-batch; database outage; embedding-provider
  failure; LLM-provider failure; process restart; lease loss *(only if runtime
  hardening enters the study)*. Plus the stage-level latency/token/cost/growth profile.

## 8. Benchmark composition (target ≈ 300 cases)

| Suite | Cases |
|---|---|
| Deletion & leakage | 60 |
| Tenant / user isolation | 50 |
| Retention, consent & legal hold | 50 |
| Admission & disclosure policy | 50 |
| Provenance & evidence integrity | 40 |
| Retrieval utility & updates | 30 |
| Failure & concurrency | 20 |
| **Total** | **300** |

Three sources: hand-authored deterministic cases; templated adversarial variants
(direct + paraphrased leakage, derived-memory leakage, tenant-id manipulation,
consent withdrawal, expiry-without-deletion, conflicting/updated facts, temporary
conversations, sensitive-audience changes); and multi-session conversational cases.
Invariant (model-independent) cases are tagged separately from quality cases.

## 9. Statistical analysis plan

- Proportions (violation/leakage/compliance rates) reported with **95% CIs**
  (Wilson interval); between-system differences via non-overlapping CIs (and a
  two-proportion test where a p-value is reported).
- Model-dependent quality metrics run over **N = 5 seeds**; report mean ± 95% CI
  (bootstrap). Deterministic invariant cases run once.
- Latency reported as p50/p95/p99 over a fixed request count; overhead as the paired
  difference vs S2 with a bootstrap CI.
- **No post-hoc thresholds.** The only numeric decision rules are H1 (0 / strict
  inequality) and H2 (Δ = 0.05 non-inferiority), both fixed above.

## 10. Reproducibility (Phase 6 preview)

Every run captures: git SHA, benchmark version, model id, provider, prompt version,
temperature, random seed, database backend, vector backend, timestamp, token usage,
cost, error/fallback counts, environment versions. Layout:

```
paper/            protocol.md, run_experiments.py, build_results.py, configs/
benchmark/        the neutral harness + cases
results/          raw/  processed/  figures/
```

One command runs everything and a second builds every table/figure from the raw
result files — **no number is hand-typed into the paper**:

```bash
python paper/run_experiments.py --config paper/configs/main.yaml
python paper/build_results.py
```

## 11. Threats to validity

- **Baseline capability mismatch.** Ungoverned systems will score `unsupported` on
  many governance cases; reporting `unsupported` separately (§5) avoids conflating
  "absent capability" with "failed capability."
- **Model/prompt confounds.** Mitigated by §4; residual per-system prompt deviations
  are logged.
- **Small-set variance.** 300 cases → wide CIs on rare-event rates; reported honestly.
- **In-memory vs Postgres.** Correctness is identical across backends; overhead (H4)
  is measured on Postgres + pgvector only (the production configuration).
- **External-system versions.** Mem0/Zep pinned by version + captured in run metadata.

## 12. Deviations log

*(Empty at pre-registration. Every change after the first result is generated is
appended here: date · what · why.)*
