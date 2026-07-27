"""Run provenance: the per-call record (§14) and the experiment manifest (§17).

No result number is trustworthy without the manifest that produced it. Records are
content-rich but **never** contain credentials.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_RUNTIME_TAG = "paper-v0.1-governance-runtime"


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:  # noqa: BLE001 — provenance is best-effort
        return ""


def repo_commit() -> str:
    return _git("rev-parse", "HEAD")


def runtime_tag_commit() -> str:
    # Records the frozen tag's commit at run time (does not move the tag).
    return _git("rev-list", "-n", "1", _RUNTIME_TAG)


@dataclass
class CallRecord:
    experiment_id: str
    case_id: str
    category: str
    repetition: int
    provider: str
    configured_model_id: str
    api_model_id: str = ""
    prompt_hash: str = ""
    dataset_hash: str = ""
    repo_commit: str = ""
    runtime_tag: str = _RUNTIME_TAG
    runtime_commit: str = ""
    start_time: str = ""
    end_time: str = ""
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int | None = None
    retry_count: int = 0
    response_id: str = ""
    raw_response: str = ""
    parsed_response: dict[str, Any] | None = None
    schema_validation: str = "ok"  # "ok" or the error class
    error_class: str | None = None
    estimated_cost_usd: float = 0.0
    sdk_version: str = ""
    python_version: str = field(default_factory=platform.python_version)
    os: str = field(default_factory=lambda: platform.platform())

    def key(self) -> tuple[str, str, int]:
        return (self.case_id, self.provider, self.repetition)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


@dataclass
class ExperimentManifest:
    experiment_id: str
    config_name: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    dataset_hash: str = ""
    prompt_hash: str = ""
    prompt_version: str = "extraction_v1"
    repo_commit: str = field(default_factory=repo_commit)
    runtime_tag: str = _RUNTIME_TAG
    runtime_commit: str = field(default_factory=runtime_tag_commit)
    seed: int = 0
    repetitions: int = 1
    providers: list[str] = field(default_factory=list)
    model_ids: dict[str, str] = field(default_factory=dict)
    matching_version: str = "v1"
    matching_threshold: float = 0.85
    pricing_version: str = ""
    python_version: str = field(default_factory=platform.python_version)
    os: str = field(default_factory=lambda: platform.platform())
    randomization: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))
