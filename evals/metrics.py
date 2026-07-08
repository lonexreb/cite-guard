"""Precision/recall/F1 and the headline retracted-claim precision gate."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from citeguard.status import StatusKind

if TYPE_CHECKING:
    from evals.harness import CaseResult

RETRACTED_PRECISION_FLOOR = 0.98


@dataclass
class ClassMetrics:
    kind: str
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def support(self) -> int:
        return self.tp + self.fn


@dataclass
class EvalReport:
    per_class: dict[str, ClassMetrics]
    confusion: dict[tuple[str, str], int]
    total: int
    passed: int
    retracted_precision: float
    unknown_rate: float
    false_retractions: list[str]  # DOIs wrongly labeled retracted
    gate_failures: list[str] = field(default_factory=list)

    @property
    def gate_ok(self) -> bool:
        return not self.gate_failures


def compute(results: list[CaseResult]) -> EvalReport:
    kinds = [k.value for k in StatusKind]
    per_class = {k: ClassMetrics(kind=k) for k in kinds}
    confusion: dict[tuple[str, str], int] = defaultdict(int)
    false_retractions: list[str] = []

    for r in results:
        expected = r.case.expected_kind
        predicted = r.predicted.value
        confusion[(expected, predicted)] += 1
        if expected == predicted:
            per_class[expected].tp += 1
        else:
            per_class[predicted].fp += 1
            per_class[expected].fn += 1
        # the cardinal sin: predicting retracted when the gold truth isn't
        if predicted == StatusKind.RETRACTED.value and expected != StatusKind.RETRACTED.value:
            false_retractions.append(r.case.doi)

    passed = sum(1 for r in results if r.ok)
    ret = per_class[StatusKind.RETRACTED.value]
    unknown = sum(1 for r in results if r.predicted is StatusKind.UNKNOWN)

    report = EvalReport(
        per_class=per_class,
        confusion=dict(confusion),
        total=len(results),
        passed=passed,
        retracted_precision=ret.precision,
        unknown_rate=unknown / len(results) if results else 0.0,
        false_retractions=false_retractions,
    )

    if false_retractions:
        report.gate_failures.append(
            f"{len(false_retractions)} false 'retracted' label(s): {false_retractions}"
        )
    if ret.precision < RETRACTED_PRECISION_FLOOR:
        report.gate_failures.append(
            f"retracted-claim precision {ret.precision:.3f} < {RETRACTED_PRECISION_FLOOR}"
        )
    for r in results:
        if not r.ok and any("MUST-NOT-BE" in v for v in r.violations):
            report.gate_failures.append(f"{r.case.doi}: {r.violations}")
    return report
