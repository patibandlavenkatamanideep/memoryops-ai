"""CLI: score raw runs → processed CSVs + statistics.json (offline)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyse_experiment
from .config import load_config
from .locking import sha256_text
from .runner import experiment_id as _exp_id

_PKG = Path(__file__).resolve().parent
_RESULTS = _PKG / "results"


def _resolve(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else _PKG / rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyse raw extraction-eval runs")
    ap.add_argument("--config", required=True)
    ap.add_argument("--experiment-id", help="defaults to <config>-<dataset_hash8>")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    dataset = _resolve(config.dataset)
    exp_id = args.experiment_id or _exp_id(config, sha256_text(dataset.read_text()))
    stats = analyse_experiment(config, dataset, _RESULTS, exp_id)
    print(f"experiment_id={exp_id}")
    print(json.dumps(stats["descriptive"], indent=2))
    print(f"processed → {_RESULTS / 'processed' / exp_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
