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
- **Prediction.** MemoryOps has **zero** violations on the two *critical* invariant
  families (deletion & leakage; tenant/user isolation) and a lower **paired** violation
  rate than each *comparable* ungoverned baseline on their common supported cases.
- **Metrics (two dimensions, reported separately).** A system that supports almost no
  governance operation must not appear "safe" by attempting nothing, so coverage and
  correctness are never collapsed into one rate:
  - **Capability coverage** = supported governance cases / all governance cases;
  - **Conditional correctness** = passed cases / *attempted supported* cases;
  - plus the overall **pass / fail / unsupported / error** outcome distribution.
  `unsupported` is reported separately and **never** enters the conditional-violation
  denominator.
- **Decision rule (pre-registered, paired).** H1 is **supported** iff MemoryOps
  (a) has **zero** violations on deletion/leakage and tenant-isolation cases;
  (b) supports all required critical operations; and (c) has a **lower paired violation
  rate than each comparable ungoverned baseline on their common supported subset**,
  tested with **McNemar's exact test** (paired binary outcomes) and **Holm** correction
  across baseline comparisons — *not* non-overlapping CIs. For a baseline with no
  meaningful common supported subset, report *"inferential comparison unavailable;
  capability unsupported"* rather than forcing an artificial p-value.

### H2 — Utility preservation
- **Prediction.** Governance preserves the retrieval/answer quality of the *identical*
  system with governance turned off.
- **Comparator (fixed, not post-hoc).** **S0-U** — MemoryOps governance-disabled,
  mechanism-matched (§3). The comparator is chosen *now*, not "the strongest baseline
  after results are visible" (which would be a moving target / selection bias).
- **Primary metric.** Per-case answer correctness on the utility suite; secondary:
  retrieval precision/recall (descriptive).
- **Decision rule (pre-registered, paired non-inferiority).** Define, per utility case,
  `d_case = correctness(S0 governed) − correctness(S0-U governance-disabled)`. H2 is
  **supported** iff the **lower bound of the one-sided 95% CI on mean `d_case` exceeds
  −0.05** (Δ = 0.05 absolute, approved). The CI is a **paired, case-level bootstrap**
  (both systems answer the same cases). **Seeds are repeated measurements within a
  case, not independent examples**: either average the seed outcomes per case before
  bootstrapping, **or** resample **cases as clusters** carrying all their seed runs
  together. Δ is fixed now and revisable only before any utility result exists.

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
- **Comparator (fixed).** Governance-attributable overhead = `metric(S0 governed) −
  metric(S0-U governance-disabled)` — the mechanism-matched difference, which isolates
  governance from orchestration / retrieval implementation / prompt / storage
  differences. The `MemoryOps − plain-vector` (S2) and `− Mem0` (S4) differences are
  kept only as *secondary* end-to-end system comparisons.
- **Primary metric.** The paired **S0 − S0-U** difference in latency (stage-broken:
  ingest / retrieve / generate), tokens, cost, and DB/audit growth.
- **Decision rule (descriptive + directional).** Governance-attributable **p50**
  overhead is **less than** provider-generation p50 (governance is not the dominant
  cost). p95/p99 reported descriptively even though the directional rule is defined at
  p50. No arbitrary absolute threshold.

## 3. Systems under test

All systems are driven through one neutral `MemorySystemAdapter` (Phase 2) so each
receives identical inputs and is scored by the identical rubric.

| # | System | Governance | Role |
|---|--------|-----------|------|
| S0 | MemoryOps (governed) @ baseline tag | full | system under study |
| **S0-U** | **MemoryOps governance-disabled (mechanism-matched)** | none | **primary matched comparator for H2 & H4 (mandatory)** |
| S1 | Full-context (all history to the model) | none | utility *ceiling* — not a persistent-memory governance baseline |
| S2 | Plain vector memory (embed → top-k → compose) | none | controlled standard-memory baseline |
| S3 | Summary memory (rolling conversation summary) | none | compression baseline |
| S4 | Mem0 | partial (product-defined) | required external system |
| S5 *(optional)* | Zep/Graphiti or other structured memory | partial | optional second external system (never blocks the paper) |

**S0-U is mandatory and is the fixed comparator for H2 and H4.** It shares S0's
extractor, embedding model, storage backend, retrieval algorithm, top-k, answer
prompt, LLM, and temperature, and **disables only the mechanisms under study**: policy-
broker enforcement, admission/output gates, governance lifecycle controls,
transactional audit evidence, and tombstone propagation (where the experiment requires
it). Without it, a reviewer can attribute any observed difference to different
retrieval implementations, prompts, or storage designs rather than to governance;
S0-U isolates the governance effect. S1–S4 are the primary *external* comparison and
S5 is optional — fewer, correctly-controlled baselines beat many partial integrations.

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
- **D — Reliability & systems performance → H3, H4.** State–audit consistency
  scenarios (H3), each executed on **Postgres + pgvector** (not only the in-memory
  backend): **API mutation rollback**; **worker mutation rollback**; **failure after
  mutation before audit**; **failure after audit insertion before commit**;
  **multi-item worker partial failure** (earlier items stay committed); **concurrent
  audit appends**; **continuous audit-chain verification**; **process termination**
  *(only if runtime hardening enters the study)*. Provider-side faults (embedding/LLM
  failure, database outage) are included for graceful-degradation coverage. H4: the
  stage-level latency / token / cost / growth profile, computed as the paired S0 − S0-U
  difference.

## 8. Benchmark composition (provisional ≈ 430–580 cases)

| Suite | Cases |
|---|---|
| Deletion & leakage | 60 |
| Tenant / user isolation | 50 |
| Retention, consent & legal hold | 50 |
| Admission & disclosure policy | 50 |
| Provenance & evidence | 40 |
| Utility & updates | **150–300** *(fixed by power analysis, below)* |
| Failure & concurrency | 30 |
| **Expected total** | **430–580** |

**Utility-suite sizing (pre-result power analysis).** The distinct utility-case count
is **not** frozen at a small value. With only 30 distinct cases a single case moves
accuracy ≈ 3.3 pts, two cases ≈ 6.7 pts, so the Δ = 0.05 non-inferiority boundary is
smaller than two cases and the paired CI would usually be too wide to support H2. Five
seeds do **not** fix this — repeated runs of the same question are correlated, not
independent examples. Therefore: **the number of distinct utility cases is fixed by a
simulation-based power analysis run *before* any utility result is generated** (target:
adequate power for the one-sided paired non-inferiority test at Δ = 0.05 under plausible
per-case effect sizes). Expected range **150–300 distinct utility cases**; seeds are
within-case repeated measurements and do not increase the independent case count.

Three sources: hand-authored deterministic cases; templated adversarial variants
(direct + paraphrased leakage, derived-memory leakage, tenant-id manipulation,
consent withdrawal, expiry-without-deletion, conflicting/updated facts, temporary
conversations, sensitive-audience changes); and multi-session conversational cases.
Invariant (model-independent) cases are tagged separately from quality cases.

## 9. Statistical analysis plan

- **H1 (correctness).** Report capability coverage, conditional correctness, and the
  pass/fail/unsupported/error distribution, each with 95% **Wilson** CIs. Between-system
  inference is **paired on the common supported subset** via **McNemar's exact test**
  with **Holm** correction across baselines — never non-overlapping CIs. Where no common
  supported subset exists, the comparison is reported *unavailable* (no forced p-value).
- **H2 (utility).** One-sided **paired case-level bootstrap** CI on the mean per-case
  correctness difference `d_case = S0 − S0-U`; supported iff the lower bound > −0.05.
  Seeds are within-case repeated measures: **average per case before bootstrapping, or
  cluster-resample cases** with all their seed runs together (never treat 5 seeds of one
  case as 5 independent examples). The distinct utility-case count is set by the §8
  power analysis. Retrieval precision/recall are descriptive.
- **H4 (overhead).** Paired **S0 − S0-U** differences; latency as p50/p95/p99 over a
  fixed request count with bootstrap CIs; S2 and S4 kept as secondary end-to-end
  comparisons. Deterministic invariant cases run once; model-dependent metrics run over
  **N = 5 seeds** aggregated per case as above.
- **No post-hoc thresholds.** The only numeric decision rules are H1 (zero critical
  violations + paired inequality) and H2 (Δ = 0.05 paired non-inferiority), both fixed
  above; H3 is binary (100%); H4 is descriptive + directional.

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
