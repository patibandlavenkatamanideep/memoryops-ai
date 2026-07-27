"""Ensure the repo root is importable so ``paper.harness`` resolves regardless of how
pytest is invoked (whole dir or a single file)."""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
