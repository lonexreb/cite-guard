"""The eval gate as a test: the cardinal rule must hold in CI."""

from evals.harness import EVALS, evaluate, load_fixtures, load_gold
from evals.metrics import compute


def test_eval_gate_passes() -> None:
    gold = load_gold(EVALS / "gold" / "gold.jsonl")
    rw_index, hijacked = load_fixtures()
    report = compute(evaluate(gold, rw_index, hijacked))
    assert report.false_retractions == [], report.false_retractions
    assert report.retracted_precision == 1.0
    assert report.gate_ok, report.gate_failures


def test_all_gold_cases_meet_expectation() -> None:
    gold = load_gold(EVALS / "gold" / "gold.jsonl")
    rw_index, hijacked = load_fixtures()
    off = [r for r in evaluate(gold, rw_index, hijacked) if not r.ok]
    assert not off, [(r.case.doi, r.violations) for r in off]
