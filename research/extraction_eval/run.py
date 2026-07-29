"""CLI: run the extraction experiment (dry-run / stub / live).

Live providers execute ONLY with ``--live``. Dry-run makes no API call. Results go to
``research/extraction_eval/results/raw/<experiment_id>/`` (append-only, resumable).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .dataset import COMPOSITIONS, composition_total
from .manifests import validate_frozen_commit
from .runner import dry_run_plan, execute

_PKG = Path(__file__).resolve().parent
_RESULTS = _PKG / "results"


def _resolve(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else _PKG / rel


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the extraction-quality experiment")
    ap.add_argument("--config", required=True)
    ap.add_argument("--dataset", help="override the config's dataset path (e.g. offline dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="plan only; no API calls, no writes")
    ap.add_argument("--live", action="store_true", help="REQUIRED to make real provider calls")
    ap.add_argument("--provider", help="run only this provider (pilot/debug only)")
    ap.add_argument("--cases", nargs="*", help="run only these case_ids")
    ap.add_argument("--no-resume", action="store_true", help="do not skip completed runs")
    args = ap.parse_args(argv)

    config = load_config(args.config)
    dataset_path = _resolve(args.dataset) if args.dataset else _resolve(config.dataset)
    if not dataset_path.exists():
        # Plan-shape validation before the dataset is authored/locked: derive the planned
        # count from the config's declared pre-registered composition. No gold is
        # fabricated; a real (non-dry) run still requires the dataset file to exist.
        if args.dry_run and not args.dataset and config.composition:
            if config.composition not in COMPOSITIONS:
                print(f"unknown composition {config.composition!r} in {args.config}")
                return 2
            validate_frozen_commit()  # frozen-subject guard still applies to plan checks
            n_cases = composition_total(config.composition)
            stats = dry_run_plan(config, n_cases)
            print(f"[DRY-RUN:PLAN] planned={stats.planned} "
                  f"stub={stats.planned - stats.skipped_not_live} "
                  f"live={stats.skipped_not_live} "
                  f"(composition={config.composition}, n_cases={n_cases}; "
                  f"dataset not yet authored)")
            return 0
        print(f"dataset not found: {dataset_path}")
        return 2

    stats = execute(
        config, dataset_path, _RESULTS,
        live=args.live, dry_run=args.dry_run, only_provider=args.provider,
        only_cases=set(args.cases) if args.cases else None, resume=not args.no_resume,
    )
    mode = "DRY-RUN" if args.dry_run else ("LIVE" if args.live else "OFFLINE (stub/skip-live)")
    print(f"[{mode}] planned={stats.planned} executed={stats.executed} "
          f"skipped_resume={stats.skipped_resume} skipped_not_live={stats.skipped_not_live} "
          f"errors={stats.errors}")
    if not args.live and not args.dry_run and stats.skipped_not_live:
        print("note: live providers were skipped — pass --live to call them (costs money).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
