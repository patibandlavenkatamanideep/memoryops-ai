"""Import path + Mem0 state isolation for the benchmark harness tests.

Two responsibilities, both needed before any test module is imported:

1. Make ``paper.harness`` resolve regardless of how pytest is invoked (whole
   directory or a single file).

2. Give Mem0 its own throwaway state directory and turn its telemetry off.

Why (2) is here rather than left to the caller
----------------------------------------------
Mem0 keeps per-user state under ``~/.mem0`` — a config file, a history database, and
a Qdrant store used for telemetry/migrations. That path is **global to the machine and
shared across every Mem0 instance in the process**, so when the suite constructs more
than one adapter the second one collides with the first on a Qdrant file lock and the
run dies with "Storage folder … is already accessed by another instance". Individual
tests pass; the suite does not.

CI worked only because the workflow happened to export ``MEM0_TELEMETRY=False``, which
meant the local run documented in ``benchmark/COMPARISON.md`` failed while CI stayed
green. A test file that only passes when its caller sets an environment variable is
not isolated — so the isolation is established here, where it applies however the
suite is invoked.

``MEM0_DIR`` moves that shared state into a per-run temporary directory, and telemetry
is disabled so no telemetry vector store is constructed at all. Both are set before
Mem0 is imported: ``mem0.memory.telemetry`` reads ``MEM0_TELEMETRY`` at module import
time, so setting it inside a fixture would be too late.

Neither setting touches what the benchmark measures. The adapter's own vector store is
a separate temporary directory it creates per instance, and the S4 results are
unchanged — this only stops two adapters fighting over one machine-global file.
"""

import atexit
import os
import pathlib
import shutil
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Must happen at import time, before any test module pulls in mem0.
if "mem0" in sys.modules:  # pragma: no cover - defensive; conftest loads first
    raise RuntimeError(
        "mem0 was imported before conftest could isolate MEM0_DIR/MEM0_TELEMETRY"
    )

_MEM0_STATE = tempfile.mkdtemp(prefix="memoryops-bench-mem0-home-")
os.environ.setdefault("MEM0_DIR", _MEM0_STATE)
os.environ.setdefault("MEM0_TELEMETRY", "False")


@atexit.register
def _cleanup_mem0_state() -> None:
    shutil.rmtree(_MEM0_STATE, ignore_errors=True)
