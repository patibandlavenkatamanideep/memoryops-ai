# Final execution checklist

Do **not** start until every box is checked.

- [ ] Amendment 001 committed; no results in it.
- [ ] Dataset authored, every case `approved`; ≥50 cases second-reviewed.
- [ ] `validate_dataset --expect locked` clean (150, correct composition).
- [ ] `lock_dataset --enforce-composition` → immutable snapshot + `.sha256` + manifest.
- [ ] `verify_lock` passes; locked file committed; `configs/final.yaml` points at it.
- [ ] Prices in `configs/pricing.yaml` verified from official docs (no nulls) **or** cost
      left unreported.
- [ ] Pilot green for all three providers; error taxonomy sane.
- [ ] Seed recorded; dry-run shows 2,250 live + 150 stub planned.

## Run (2,400 total: 150 stub + 2,250 live — live calls cost money)
Run the **single interleaved schedule** — do NOT run one provider fully before the next.
The first live invocation builds and persists `results/raw/<exp>/schedule.json` (case
order shuffled per repetition, provider order rotated); every resume reuses it.
```bash
# Verify the plan first (offline; must report planned=2400):
python -m research.extraction_eval.run --config configs/final.yaml --dry-run

# Execute the whole randomised schedule (stub control + all live providers interleaved):
python -m research.extraction_eval.run --config configs/final.yaml --live   # resumes if interrupted

python -m research.extraction_eval.analyse --config configs/final.yaml
python -m research.extraction_eval.build_paper_artifacts --config configs/final.yaml
```
`--provider <name>` is for the **pilot / debugging only** — it runs a single-provider
subset and does not persist the master schedule.
No thresholds change after seeing results. Dataset errors → errata + new version, never in-place edits.
