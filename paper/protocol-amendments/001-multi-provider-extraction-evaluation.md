# Amendment 001 — Multi-Provider Extraction Evaluation

- **Date:** 2026-07-27
- **Status:** Pre-registration (written **before** any locked comparative result is observed)
- **Amends:** `paper/protocol.md`
- **Frozen runtime subject:** tag `paper-v0.1-governance-runtime` (immutable; not moved by this work)

> This amendment contains **no comparative results**. It specifies the expanded
> extraction evaluation in advance so outcomes cannot be reverse-engineered into a
> favorable story.

## 1. Relationship to the existing pilot

The paper currently reports a **25-turn extraction pilot** using a deterministic stub
and one live model (Gemini 2.5 Flash). That pilot is **retained as pilot evidence** and
is explicitly labelled preliminary. This amendment specifies a larger, provider-diverse
evaluation that will **replace the headline extraction claim**; it does not delete the
pilot.

## 2. Purpose

To **evaluate extraction quality across providers**, not to select a winner after
seeing results. The comparison is descriptive and pre-registered; no model is added or
removed on the basis of observed accuracy.

## 3. Design (fixed before results)

- The locked evaluation contains **150 independent cases**.
- There are **30 development cases** (used only for harness/prompt debugging, never scored
  in the headline result).
- There are **5 repetitions** per locked case and per live model.
- The **case — not the individual model call — is the independent statistical unit**.
  Five repetitions of one case are repeated measurements, not five independent samples.
- The **deterministic stub is an engineering control**, not a live-model baseline. It runs
  once per case.
- Live model families under test: three (a continuity model plus two others). Exact
  **model IDs are loaded from the frozen experiment config** (`configs/final.yaml`), and
  every run manifest records the configured *and* API-reported model IDs.

## 4. Metrics (fixed before the run)

- **Primary:** memory-atom precision, recall, F1; exact turn-level set match; false-memory
  and missed-memory rates — all computed by **deterministic matching** (§15 of the harness),
  never an LLM judge.
- **Secondary:** behavioural accuracy (no-op, multi-memory split, update, contradiction,
  temporal, policy-disposition, memory-type); reliability (structured-output success,
  schema-validation failure, refusal, truncation, empty, provider error, retry); operational
  (p50/p95/p99 latency, tokens, estimated cost, cost per case, cost per correct atom).
- A semantic/embedding score may be reported **only** as a secondary sensitivity analysis;
  it does **not** replace the deterministic primary metric.

## 5. Validity commitments

- **Invalid structured output is recorded as an error** and is **not** silently regenerated.
  Only transient transport failures (429/5xx/timeout) are retried, with recorded retry count.
- **No provider fallback** — one provider's failure is never answered by another provider.
- **Extraction and storage disposition are scored separately.** A sensitive candidate that is
  correctly marked `block` is an extraction success, not a failure.
- **Human agreement** is measured on **at least 50 blinded locked cases**; target Cohen's
  kappa ≥ 0.80 on key categorical fields (a *target*, not a result).
- **No thresholds may change after observing locked-set results.** Matching thresholds and the
  matching version are frozen in the experiment config.
- **Model outputs may never be used to revise gold labels.**
- **Dataset errors found after locking** are recorded in a versioned **errata** file and a new
  dataset version is minted; the locked snapshot is never edited in place.

## 6. Independence of authorship and labels

Draft cases and authoring tooling may be produced programmatically, but a case becomes
**gold only after explicit human approval**. A second reviewer reviews at least 50 locked
cases. No claim of independent annotation is made until reviewer data exists.

## 7. Out of scope

Runtime changes, retrieval/vector work, SDK/UI/API-contract changes, and the frozen tag are
out of scope. The production chat request path is not modified for this study.
