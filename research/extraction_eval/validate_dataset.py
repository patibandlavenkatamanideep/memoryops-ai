"""CLI: validate a dataset file (offline, no keys)."""

from __future__ import annotations

import argparse
import sys

from .dataset import (
    DEVELOPMENT_COMPOSITION,
    LOCKED_COMPOSITION,
    PILOT_COMPOSITION,
    category_counts,
    load_cases,
    validate_cases,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate extraction-eval dataset cases")
    ap.add_argument("--dataset", required=True)
    ap.add_argument(
        "--expect", default="none",
        choices=["none", "draft", "pilot", "development", "locked"],
        help="draft = structural only (never enforces the locked composition); "
             "pilot/development/locked enforce their fixed composition.",
    )
    args = ap.parse_args(argv)

    cases = load_cases(args.dataset)
    # 'draft' and 'none' impose NO composition — draft data is never validated as locked.
    expected = {
        "pilot": PILOT_COMPOSITION,
        "development": DEVELOPMENT_COMPOSITION,
        "locked": LOCKED_COMPOSITION,
    }.get(args.expect)
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
