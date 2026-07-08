"""Run the eval harness offline and print precision/recall.

    uv run python -m evals.run

Exits non-zero if the retracted-claim precision gate fails (any gold non-
retracted case labeled retracted, precision < floor, or a must-not-be
violation) — so CI enforces the cardinal rule.
"""

from __future__ import annotations

import json
import sys

from evals.harness import EVALS, evaluate, load_fixtures, load_gold
from evals.metrics import compute


def main() -> int:
    gold = load_gold(EVALS / "gold" / "gold.jsonl")
    rw_index, hijacked = load_fixtures()
    results = evaluate(gold, rw_index, hijacked)
    report = compute(results)

    print(f"\nCiteGuard eval — {report.total} gold cases, {report.passed} passed\n")
    print(f"{'class':<22}{'P':>7}{'R':>7}{'F1':>7}{'support':>9}")
    print("-" * 52)
    for kind, m in report.per_class.items():
        if m.support == 0 and m.fp == 0:
            continue
        print(f"{kind:<22}{m.precision:>7.3f}{m.recall:>7.3f}{m.f1:>7.3f}{m.support:>9}")

    print("\nHEADLINE")
    print(f"  retracted-claim precision : {report.retracted_precision:.3f}  (the cardinal metric)")
    print(f"  unknown rate              : {report.unknown_rate:.3f}  (cost of conservatism)")
    print(f"  false retractions         : {len(report.false_retractions)}")

    failures = [r for r in results if not r.ok]
    if failures:
        print(f"\n{len(failures)} case(s) off expectation:")
        for r in failures:
            print(f"  {r.case.doi} [{','.join(r.case.tags)}]: {'; '.join(r.violations)}")

    results_dir = EVALS / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "latest.json").write_text(
        json.dumps(
            {
                "total": report.total,
                "passed": report.passed,
                "retracted_precision": report.retracted_precision,
                "unknown_rate": report.unknown_rate,
                "per_class": {
                    k: {
                        "precision": m.precision,
                        "recall": m.recall,
                        "f1": m.f1,
                        "support": m.support,
                    }
                    for k, m in report.per_class.items()
                    if m.support or m.fp
                },
                "gate_failures": report.gate_failures,
            },
            indent=2,
        )
    )

    if report.gate_ok:
        print("\n✅ GATE PASSED — no false retractions.\n")
        return 0
    print("\n❌ GATE FAILED:")
    for f in report.gate_failures:
        print(f"  - {f}")
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
