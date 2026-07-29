"""Versioned experiment configuration (frozen before a run).

Model IDs, repetitions, matching version/threshold, prompt file, seed, and dataset
path live here — not scattered through code. Loaded from YAML; credentials are never
part of config (read from the environment at call time).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PyYAML is required to load experiment configs") from exc
    return yaml.safe_load(path.read_text()) or {}


@dataclass
class ProviderSpec:
    name: str
    model_id: str
    live: bool


@dataclass
class ExperimentConfig:
    name: str
    dataset: str
    prompt_file: str
    repetitions: int
    seed: int
    matching_version: str
    matching_threshold: float
    pricing_file: str
    # Pre-registered composition this experiment targets (see dataset.COMPOSITIONS).
    # Lets --dry-run validate the plan shape before the dataset is authored/locked.
    composition: str | None = None
    providers: list[ProviderSpec] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def prompt_path(self) -> Path:
        p = Path(self.prompt_file)
        return p if p.is_absolute() else (_ROOT / self.prompt_file)

    def prompt_text(self) -> str:
        return self.prompt_path.read_text()

    def prompt_hash(self) -> str:
        return hashlib.sha256(self.prompt_text().encode()).hexdigest()

    def live_providers(self) -> list[ProviderSpec]:
        return [p for p in self.providers if p.live]

    def control_providers(self) -> list[ProviderSpec]:
        return [p for p in self.providers if not p.live]


def load_config(path: str | Path) -> ExperimentConfig:
    path = Path(path)
    data = _load_yaml(path)
    providers = [
        ProviderSpec(name=p["name"], model_id=p.get("model_id", p["name"]), live=bool(p.get("live", False)))
        for p in data.get("providers", [])
    ]
    return ExperimentConfig(
        name=data["name"],
        dataset=data["dataset"],
        prompt_file=data.get("prompt_file", "prompts/extraction_v1.txt"),
        repetitions=int(data.get("repetitions", 1)),
        seed=int(data.get("seed", 20260727)),
        matching_version=str(data.get("matching_version", "v1")),
        matching_threshold=float(data.get("matching_threshold", 0.85)),
        pricing_file=data.get("pricing_file", "configs/pricing.yaml"),
        composition=data.get("composition"),
        providers=providers,
        raw=data,
    )
