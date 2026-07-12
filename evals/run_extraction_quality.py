#!/usr/bin/env python3
"""Extraction-quality eval — per-provider precision / recall of memory extraction.

The rest of the eval harness proves *governance*; this measures *extraction quality*:
given hand-labeled conversation turns, how well does each provider pull the right
memories out? It scores the deterministic stub by default (offline, no keys) and any
real provider you have a key for, so the benchmark becomes an honest instrument —
the stub is expected to trail real models, and showing that is the point.

Matching (fuzzy, content-level):
  * an *expected fact* is COVERED if its key tokens all appear in some extracted
    memory's content (→ drives recall);
  * an *extracted memory* is RELEVANT if it covers at least one expected fact
    (→ drives precision).
  * a turn with no expected facts (a question / chit-chat) should extract nothing;
    any extraction there is a false positive.

Usage:
  python evals/run_extraction_quality.py                     # stub only (offline)
  python evals/run_extraction_quality.py --provider openai   # needs OPENAI_API_KEY
  python evals/run_extraction_quality.py --provider stub openai anthropic
  python evals/run_extraction_quality.py --json
  python evals/run_extraction_quality.py --md benchmark/EXTRACTION_QUALITY.md
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "services" / "api"))

_DATASET = _REPO_ROOT / "evals" / "datasets" / "extraction_golden.jsonl"
_STOP = {"i", "a", "an", "the", "to", "of", "my", "is", "are", "in", "on", "and", "me"}
_TOKEN = re.compile(r"[a-z0-9.]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOP}


def _covers(fact: str, contents: list[str]) -> bool:
    """A fact is covered if its key tokens all appear within one memory's content."""
    want = _tokens(fact)
    return any(want <= _tokens(c) or fact.lower() in c.lower() for c in contents)


def _load_cases() -> list[dict]:
    return [json.loads(line) for line in _DATASET.read_text().splitlines() if line.strip()]


@dataclass
class Score:
    provider: str
    tp: int = 0            # relevant extracted memories
    extracted: int = 0     # total extracted memories
    expected: int = 0      # total expected facts
    covered: int = 0       # expected facts found
    noop_ok: int = 0       # no-memory turns handled correctly
    noop_total: int = 0
    multi_ok: int = 0      # compound turns where >=2 memories were extracted
    multi_total: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.tp / self.extracted if self.extracted else 1.0

    @property
    def recall(self) -> float:
        return self.covered / self.expected if self.expected else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _build_provider(provider_name: str):
    """Build a provider by name (keys are read from env by Settings)."""
    from app.core.config import Settings
    from app.llm.registry import build_llm_provider

    return build_llm_provider(Settings(llm_provider=provider_name))


def _extract(provider, settings, message: str) -> list[str]:
    from app.llm import extract_memories

    outcome = extract_memories(provider, message, settings=settings)
    return [m.content for m in outcome.memories]


def score_provider(provider_name: str, cases: list[dict]) -> Score:
    from app.core.config import Settings

    s = Score(provider=provider_name)
    settings = Settings(llm_provider=provider_name)
    provider = _build_provider(provider_name)
    for case in cases:
        facts = case.get("expected_facts", [])
        try:
            contents = _extract(provider, settings, case["message"])
        except Exception as exc:  # noqa: BLE001 — record, keep scoring
            s.errors.append(f"{case['id']}: {type(exc).__name__}")
            continue
        s.extracted += len(contents)
        s.expected += len(facts)
        s.covered += sum(1 for f in facts if _covers(f, contents))
        s.tp += sum(1 for c in contents if any(_covers(f, [c]) for f in facts))
        if not facts:
            s.noop_total += 1
            s.noop_ok += 1 if not contents else 0
        if len(facts) >= 2:
            s.multi_total += 1
            s.multi_ok += 1 if len(contents) >= 2 else 0
    return s


def _table(scores: list[Score]) -> str:
    rows = [
        "| Provider | Precision | Recall | F1 | No-op handled | Multi-memory turns |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for s in scores:
        noop = f"{s.noop_ok}/{s.noop_total}" if s.noop_total else "—"
        multi = f"{s.multi_ok}/{s.multi_total}" if s.multi_total else "—"
        rows.append(
            f"| {s.provider} | {s.precision:.2f} | {s.recall:.2f} | {s.f1:.2f} | {noop} | {multi} |"
        )
    return "\n".join(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", nargs="+", default=["stub"],
                    help="providers to score (stub is always offline-safe)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", type=str, default=None)
    ap.add_argument("--min-recall", type=float, default=0.0,
                    help="exit non-zero if any scored provider's recall is below this")
    args = ap.parse_args()

    cases = _load_cases()
    scores: list[Score] = []
    for name in args.provider:
        # Real providers need a key; skip (don't fail) when absent so CI stays green.
        key_env = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                   "gemini": "GEMINI_API_KEY"}.get(name)
        if key_env and not os.getenv(key_env):
            print(f"SKIP provider '{name}': {key_env} not set")
            continue
        scores.append(score_provider(name, cases))

    if args.json:
        print(json.dumps([{
            "provider": s.provider, "precision": round(s.precision, 3),
            "recall": round(s.recall, 3), "f1": round(s.f1, 3),
            "noop": [s.noop_ok, s.noop_total], "multi": [s.multi_ok, s.multi_total],
            "errors": s.errors,
        } for s in scores], indent=2))
        return 0

    title = f"# Extraction quality ({len(cases)} labeled turns)\n"
    body = title + "\n" + _table(scores) + "\n"
    print(body)
    if args.md:
        Path(args.md).write_text(body)
        print(f"wrote {args.md}")

    below = [s for s in scores if s.recall < args.min_recall]
    if below:
        for s in below:
            print(f"FAIL: {s.provider} recall {s.recall:.2f} < {args.min_recall:.2f}")
        return 1
    errored = [s for s in scores if s.errors]
    if errored:
        for s in errored:
            print(f"FAIL: {s.provider} had errors: {s.errors[:3]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
