# Annotation & human-review guide

Goal: ≥50 blinded locked cases independently reviewed; target Cohen's kappa ≥ 0.80 on the
key categorical fields (a target, not a claim).

## Workflow
1. `human_review.stratified_sample(cases, n=50, seed)` → provider-blind package
   (`export_annotation_package`): case content + gold + empty reviewer fields.
2. Reviewer fills `reviewer.expected_noop` and, per atom, memory_type / operation /
   should_store / policy_disposition — **independently**.
3. `import_annotations` → `validate_completeness` → `compute_agreement` (percent + kappa).
4. Disagreements → `adjudication_template`; a **second** reviewer adjudicates.
5. Model outputs never enter this loop and never revise gold.

Only after reviewer data exists may the paper claim independent review.
