"""Per-case scoring built on deterministic matching (§16 metrics).

Extraction correctness (did the right atoms come out?) and metadata/behaviour
(memory-type, operation, policy-disposition, no-op) are scored as separate signals so a
sensitive atom correctly marked ``block`` counts as extraction success. A case with a
provider error is scored as an error, not a zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .matching import match_atoms
from .schema import ExtractionOutput, Gold


@dataclass
class CaseScore:
    case_id: str
    category: str
    provider: str
    repetition: int
    scored: bool = True  # False when the call errored (excluded from accuracy means)
    error_class: str | None = None
    expected_noop: bool = False
    predicted_noop: bool = False
    tp: int = 0  # matched atoms
    fp: int = 0  # false memories
    fn: int = 0  # missed memories
    exact_set_match: bool = False
    noop_correct: bool | None = None
    # metadata agreement over matched atoms
    type_correct: int = 0
    operation_correct: int = 0
    should_store_correct: int = 0
    policy_correct: int = 0
    matched: int = 0
    borderline: int = 0

    @property
    def precision(self) -> float | None:
        d = self.tp + self.fp
        return self.tp / d if d else None

    @property
    def recall(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)


@dataclass
class ScoringConfig:
    threshold: float = 0.85
    version: str = "v1"


def score_case(
    output: ExtractionOutput | None,
    gold: Gold,
    *,
    provider: str,
    case_id: str,
    category: str,
    repetition: int,
    error_class: str | None = None,
    cfg: ScoringConfig | None = None,
) -> CaseScore:
    cfg = cfg or ScoringConfig()
    sc = CaseScore(
        case_id=case_id, category=category, provider=provider, repetition=repetition,
        expected_noop=gold.expected_noop,
    )
    if output is None:
        sc.scored = False
        sc.error_class = error_class or "unknown_error"
        return sc

    sc.predicted_noop = output.is_noop
    if gold.expected_noop:
        sc.noop_correct = output.is_noop
        # Any atom emitted on a no-op turn is a false memory.
        sc.fp = len(output.memories)
        sc.exact_set_match = output.is_noop
        return sc

    pred_texts = [m.memory_text for m in output.memories]
    res = match_atoms(pred_texts, gold.atoms, threshold=cfg.threshold)
    sc.tp = len(res.matches)
    sc.fp = len(res.unmatched_pred)
    sc.fn = len(res.unmatched_gold)
    sc.matched = len(res.matches)
    sc.borderline = len(res.borderline)
    sc.exact_set_match = sc.fp == 0 and sc.fn == 0 and sc.tp == len(gold.atoms)

    for m in res.matches:
        pred = output.memories[m.pred_index]
        g = gold.atoms[m.gold_index]
        sc.type_correct += int(pred.memory_type == g.memory_type)
        sc.operation_correct += int(pred.operation == g.operation)
        sc.should_store_correct += int(pred.should_store == g.should_store)
        sc.policy_correct += int(pred.policy_disposition == g.policy_disposition)
    return sc


@dataclass
class Aggregate:
    """Micro-averaged extraction metrics + behavioural/reliability rates over a set of
    case scores (one provider, or one provider×category)."""

    n_cases: int = 0
    n_scored: int = 0
    n_errors: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    exact_matches: int = 0
    noop_total: int = 0
    noop_correct: int = 0
    matched: int = 0
    type_correct: int = 0
    operation_correct: int = 0
    policy_correct: int = 0
    error_classes: dict[str, int] = field(default_factory=dict)

    @property
    def precision(self) -> float | None:
        d = self.tp + self.fp
        return self.tp / d if d else None

    @property
    def recall(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if not p or not r:
            return None
        return 2 * p * r / (p + r)

    @property
    def exact_match_rate(self) -> float | None:
        return self.exact_matches / self.n_scored if self.n_scored else None

    @property
    def false_memory_rate(self) -> float | None:
        d = self.tp + self.fp
        return self.fp / d if d else None

    @property
    def missed_memory_rate(self) -> float | None:
        d = self.tp + self.fn
        return self.fn / d if d else None

    @property
    def noop_accuracy(self) -> float | None:
        return self.noop_correct / self.noop_total if self.noop_total else None

    @property
    def type_accuracy(self) -> float | None:
        return self.type_correct / self.matched if self.matched else None

    @property
    def policy_accuracy(self) -> float | None:
        return self.policy_correct / self.matched if self.matched else None


def aggregate(scores: list[CaseScore]) -> Aggregate:
    agg = Aggregate(n_cases=len(scores))
    for s in scores:
        if not s.scored:
            agg.n_errors += 1
            agg.error_classes[s.error_class or "unknown_error"] = (
                agg.error_classes.get(s.error_class or "unknown_error", 0) + 1
            )
            continue
        agg.n_scored += 1
        agg.tp += s.tp
        agg.fp += s.fp
        agg.fn += s.fn
        agg.exact_matches += int(s.exact_set_match)
        agg.matched += s.matched
        agg.type_correct += s.type_correct
        agg.operation_correct += s.operation_correct
        agg.policy_correct += s.policy_correct
        if s.expected_noop:
            agg.noop_total += 1
            agg.noop_correct += int(bool(s.noop_correct))
    return agg
