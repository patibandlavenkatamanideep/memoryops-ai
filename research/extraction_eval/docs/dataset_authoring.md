# Dataset authoring guide

Cases are JSONL of the `schema.Case` model. **Model-generated cases are drafts, never
gold.** Authoring status flows: `draft → authored → approved`; review status
`unreviewed → reviewed → adjudicated`.

## Compose
- Development: 30 cases (proportional across the 7 categories) — harness/prompt debugging only.
- Locked: 150 cases — no_persistent_memory 25, single_memory 30, multi_memory 35,
  update_contradiction 20, temporal_negation 15, low_utility_ambiguous 10,
  sensitive_policy_boundary 15.

## Each case
`case_id, category, difficulty, conversation[{turn_id,role,content}], target_turn_id,
gold{expected_noop, atoms[atom_id, memory_text, accepted_phrasings, memory_type, subject,
operation, should_store, policy_disposition, supersedes, source_turn_ids], reason},
annotator_notes, authoring_status, review_status, dataset_version`.

Rules: a no-op case has **no** atoms; every `source_turn_ids` must exist; use canonical
`memory_type`; give `accepted_phrasings` so deterministic matching is fair; for sensitive
content set `should_store=false`, `policy_disposition=block` (extraction still succeeds).

## Stages & validation
- `datasets/development/cases.jsonl` — 15-case pilot/integration set (`--expect pilot`).
- `datasets/draft/candidate_cases.jsonl` — authoring workspace toward the locked set
  (`--expect draft` = structural only; **draft is never validated as locked**).
- `datasets/locked/extraction_eval_v1.jsonl` — created by `lock_dataset` (`--expect locked`).

```bash
python -m research.extraction_eval.validate_dataset --dataset <file> --expect draft   # structural
python -m research.extraction_eval.validate_dataset --dataset <file> --expect locked  # 150 composition
```
Fix every reported problem before requesting review. A model-generated draft (e.g. from
`author_candidates`) is **not gold** and must be human-authored + approved before locking.
