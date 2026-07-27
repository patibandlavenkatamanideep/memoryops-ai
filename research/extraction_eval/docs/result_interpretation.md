# Result interpretation guide

- **Primary** = deterministic atom precision/recall/F1 + exact-set match. Report per
  provider with **case-level** bootstrap CIs (repetitions grouped). Paired provider
  differences use the shared cases; apply Holm across the comparison family.
- **Extraction ≠ storage.** A sensitive atom marked `block` is an extraction success.
  Read `policy_accuracy` separately from precision/recall.
- **Unsupported ≠ fail.** Report capability coverage separately.
- **Stub answers are a control**, not a live baseline; never rank the stub against models
  as if it were one.
- **Reliability** (structured-output success, schema-validation failure, refusal,
  truncation, empty, provider error, retry) is first-class — a high-F1 model with a high
  refusal rate is not "better" unqualified.
- **Cost** is derived metadata; **raw tokens** are the evidence. If prices are null,
  report tokens only.
- Secondary embedding scores are sensitivity analyses, never the headline.
