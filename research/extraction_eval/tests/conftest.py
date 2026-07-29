"""Make `research.extraction_eval` (repo root) and the app (services/api) importable so
the offline tests run from anywhere with no keys."""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[3]
for p in (_ROOT, _ROOT / "services" / "api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
