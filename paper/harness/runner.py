"""Case runner + scorecard for the governance-runtime study.

Drives one system at a time through a case set and classifies each case into the
neutral ``Outcome`` vocabulary (protocol §5). Capability coverage and correctness are
reported as *separate* dimensions so a system that supports little is never made to
look "safe" by attempting nothing:

* a case whose ``requires`` a system lacks → ``unsupported`` (a coverage finding);
* an operation that errors → ``error``;
* otherwise the probe decides ``pass`` / ``fail`` (a recalled forbidden string is a
  governance violation → ``fail``).

Scored from *retrieved* memories, so results are meaningful under the stub LLM.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .cases import Case, ForgetStep, IngestStep
from .types import Outcome, OpStatus, RunManifest


@dataclass
class CaseResult:
    case_id: str
    suite: str
    system: str
    outcome: Outcome
    detail: str = ""


def run_case(adapter, case: Case) -> CaseResult:
    missing = case.requires - adapter.capabilities()
    if missing:
        return CaseResult(
            case.id, case.suite, adapter.name, Outcome.UNSUPPORTED,
            f"missing {sorted(c.value for c in missing)}",
        )

    adapter.reset()
    labels: dict[str, list[str]] = {}
    for step in case.steps:
        if isinstance(step, IngestStep):
            r = adapter.ingest(step.scope, step.message)
            if r.status is OpStatus.ERROR:
                return CaseResult(case.id, case.suite, adapter.name, Outcome.ERROR, "ingest error")
            if step.label:
                labels[step.label] = r.memory_ids
        elif isinstance(step, ForgetStep):
            ids = labels.get(step.label, [])
            # No id means nothing was stored to begin with (e.g. governance blocked it
            # at admission) — not an error; the probe still decides the outcome.
            for mid in ids:
                fr = adapter.forget(step.scope, mid)
                if fr.status is OpStatus.UNSUPPORTED:
                    return CaseResult(
                        case.id, case.suite, adapter.name, Outcome.UNSUPPORTED,
                        "forget unsupported",
                    )
                if fr.status is OpStatus.ERROR:
                    return CaseResult(
                        case.id, case.suite, adapter.name, Outcome.ERROR, "forget error"
                    )

    probe = adapter.query(case.probe_scope, case.probe)
    if probe.status is OpStatus.ERROR:
        return CaseResult(case.id, case.suite, adapter.name, Outcome.ERROR, "query error")
    leaked = _leaks(probe, case.forbidden)
    return CaseResult(
        case.id, case.suite, adapter.name,
        Outcome.FAIL if leaked else Outcome.PASS,
        "forbidden string recalled" if leaked else "",
    )


def _leaks(probe, forbidden: str) -> bool:
    f = forbidden.lower()
    if f in (probe.answer or "").lower():
        return True
    return any(f in (m.content or "").lower() for m in probe.retrieved)


@dataclass
class SuiteRun:
    manifest: RunManifest
    results: list[CaseResult] = field(default_factory=list)


def run_suite(adapter_factories, cases: list[Case]) -> list[CaseResult]:
    """Run every case against every system (one system fully, then the next)."""
    results: list[CaseResult] = []
    for factory in adapter_factories:
        adapter = factory()
        for case in cases:
            results.append(run_case(adapter, case))
    return results


def tally(results: list[CaseResult]) -> dict[str, dict[str, int]]:
    """Per-system counts of pass/fail/unsupported/error."""
    out: dict[str, dict[str, int]] = defaultdict(lambda: {o.value: 0 for o in Outcome})
    for r in results:
        out[r.system][r.outcome.value] += 1
    return dict(out)


def scorecard(results: list[CaseResult]) -> str:
    """A compact, deterministic text scorecard (systems × outcome counts)."""
    counts = tally(results)
    cols = [o.value for o in Outcome]
    width = max((len(s) for s in counts), default=6)
    header = "system".ljust(width) + "  " + "  ".join(c.rjust(11) for c in cols)
    lines = [header, "-" * len(header)]
    for system in sorted(counts):
        row = counts[system]
        lines.append(
            system.ljust(width) + "  " + "  ".join(str(row[c]).rjust(11) for c in cols)
        )
    return "\n".join(lines)


def build_manifest(system: str, *, benchmark_version: str = "0.1") -> RunManifest:
    """Capture per-run provenance (protocol §6/§10). Content-free."""
    import platform
    import subprocess
    from datetime import UTC, datetime

    def _sha() -> str:
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except Exception:  # noqa: BLE001 — provenance is best-effort
            return ""

    return RunManifest(
        system=system,
        benchmark_version=benchmark_version,
        git_sha=_sha(),
        model_id="stub",
        provider="stub",
        storage_backend="memory",
        vector_backend="memory",
        timestamp=datetime.now(UTC).isoformat(),
        env={"python": platform.python_version()},
    )
