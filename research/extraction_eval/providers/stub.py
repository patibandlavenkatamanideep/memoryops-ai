"""Deterministic stub provider — the engineering control (not a live-model baseline).

Reuses MemoryOps' production offline heuristic (`app.llm.fallback.heuristic_extract`)
so the control is the *actual* shipped no-key extraction, mapped into the neutral
schema. No network, no keys, fully deterministic → runs once per case.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..errors import ErrorClass
from ..schema import ExtractionOutput, MemoryAtom, Operation, PolicyDisposition
from .base import ProviderResult

_API = Path(__file__).resolve().parents[3] / "services" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))


class StubProvider:
    name = "stub"
    configured_model_id = "stub"

    def available(self) -> bool:
        return True

    def is_live(self) -> bool:
        return False

    def parse(self, raw_text: str):  # the stub emits already-valid JSON
        from .base import parse_json_output

        return parse_json_output(raw_text)

    def extract(self, *, prompt: str, conversation: list[dict], target_turn_id: str) -> ProviderResult:
        target = next((t for t in conversation if t.get("turn_id") == target_turn_id), None)
        content = (target or {}).get("content", "")
        from app.llm.fallback import heuristic_extract

        atoms = [
            MemoryAtom(
                memory_text=m.content,
                memory_type=m.type.value,
                subject="user",
                operation=Operation.create,
                should_store=True,
                policy_disposition=PolicyDisposition.save,
                source_turn_ids=[target_turn_id],
            )
            for m in heuristic_extract(content)
        ]
        output = ExtractionOutput(memories=atoms)
        return ProviderResult(
            output=output,
            raw_text=output.model_dump_json(),
            api_model_id="stub",
            sdk_version="n/a",
            finish_reason="stop",
        )

    # Exposed so tests can classify the deterministic path uniformly.
    _empty_error = ErrorClass.empty_response
