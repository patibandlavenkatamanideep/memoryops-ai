"""CLI: lock an approved draft dataset into an immutable, hash-protected snapshot.

Requires every case ``authoring_status='approved'`` (human step) and refuses to
overwrite an existing lock — re-locking mints a new version + errata (§7).
"""

from __future__ import annotations

import argparse
import sys

from .dataset import LOCKED_COMPOSITION
from .locking import LockError, lock_dataset


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lock an approved extraction-eval dataset")
    ap.add_argument("--input", required=True, help="approved draft JSONL")
    ap.add_argument("--output", required=True, help="locked snapshot path")
    ap.add_argument("--version", required=True, help="dataset version, e.g. extraction_eval_v1")
    ap.add_argument("--enforce-composition", action="store_true",
                    help="require the 150-case locked composition")
    args = ap.parse_args(argv)

    expected = LOCKED_COMPOSITION if args.enforce_composition else None
    try:
        manifest = lock_dataset(args.input, args.output, version=args.version, expected_counts=expected)
    except LockError as exc:
        print(f"LOCK REFUSED:\n{exc}")
        return 1
    print(f"LOCKED {args.output}")
    print(f"  version={manifest.version} cases={manifest.case_count} atoms={manifest.atom_count}")
    print(f"  sha256={manifest.sha256}")
    print(f"  categories={manifest.category_counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
