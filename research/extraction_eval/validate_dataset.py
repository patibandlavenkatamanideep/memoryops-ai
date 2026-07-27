"""CLI: validate a dataset file (offline, no keys)."""

from __future__ import annotations

import argparse
import sys

from .dataset import DEVELOPMENT_COMPOSITION, LOCKED_COMPOSITION, category_counts, load_cases, validate_cases


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate extraction-eval dataset cases")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--expect", choices=["locked", "development", "none"], default="none")
    args = ap.parse_args(argv)

    cases = load_cases(args.dataset)
    expected = {"locked": LOCKED_COMPOSITION, "development": DEVELOPMENT_COMPOSITION}.get(args.expect)
    problems = validate_cases(cases, expected_counts=expected)
    print(f"cases: {len(cases)}  category_counts: {category_counts(cases)}")
    if problems:
        print("INVALID:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("OK: dataset valid" + ("" if expected is None else " (composition matches)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
