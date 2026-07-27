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

## Run (2,250 live calls — costs money)
```bash
python -m research.extraction_eval.run --config configs/final.yaml --provider stub
for p in gemini openai anthropic; do
  python -m research.extraction_eval.run --config configs/final.yaml --provider $p --live
done   # each resumes; order is randomised + seed-recorded
python -m research.extraction_eval.analyse --config configs/final.yaml
python -m research.extraction_eval.build_paper_artifacts --config configs/final.yaml
```
No thresholds change after seeing results. Dataset errors → errata + new version, never in-place edits.
