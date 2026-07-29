"""CLI: generate paper tables + figures from scored results (offline).

Every artefact derives from result files; nothing is hand-typed. Also writes a
clearly-marked placeholder listing which paper sections need real results before any
claim is updated — it never invents findings.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from .analysis import load_runs, score_runs
from .config import load_config
from .locking import sha256_text
from .reporting import write_figures, write_tables
from .runner import experiment_id as _exp_id

_PKG = Path(__file__).resolve().parent
_RESULTS = _PKG / "results"

_PLACEHOLDER = """# Paper update placeholder — DO NOT paste numbers by hand

Generated tables/figures for experiment `{exp}` are under:
- tables:  results/tables/{exp}/
- figures: results/figures/{exp}/

Sections to update **only after** the locked run + human annotations exist:
- Extraction-quality results table (replace the 25-turn pilot headline).
- Provider comparison figure (precision/recall/F1/exact-match).
- Reliability + cost/latency tables.
- Human-agreement (Cohen's kappa) paragraph.
- Error-analysis appendix.

Do not modify the abstract/conclusion with placeholder findings. The current numbers,
if produced from the stub or fixtures only, are infrastructure validation — NOT the
study result.
"""


def _resolve(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else _PKG / rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build paper tables + figures")
    ap.add_argument("--config", required=True)
    ap.add_argument("--experiment-id")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    dataset = _resolve(config.dataset)
    exp_id = args.experiment_id or _exp_id(config, sha256_text(dataset.read_text()))

    runs = load_runs(_RESULTS / "raw" / exp_id)
    scores = score_runs(runs, dataset, threshold=config.matching_threshold)
    by_provider = defaultdict(list)
    for s in scores:
        by_provider[s.provider].append(s)

    tables = write_tables(dict(by_provider), _RESULTS / "tables" / exp_id)
    figures = write_figures(dict(by_provider), _RESULTS / "figures" / exp_id)
    (_RESULTS / "tables" / exp_id / "PAPER_UPDATE_PLACEHOLDER.md").write_text(_PLACEHOLDER.format(exp=exp_id))

    print(f"experiment_id={exp_id}  runs={len(runs)}  providers={sorted(by_provider)}")
    print(f"tables: {len(tables)} files → {_RESULTS / 'tables' / exp_id}")
    print(f"figures: {len(figures)} files → {_RESULTS / 'figures' / exp_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
