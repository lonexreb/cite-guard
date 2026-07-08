"""Offline eval harness: resolve gold cases from committed fixtures only.

No network. Each gold DOI's signals are assembled from:
  - evals/fixtures/rw_gold.csv         (real Retraction Watch rows)
  - evals/fixtures/openalex/{slug}.json (one recorded work, optional)
  - evals/fixtures/crossref/{slug}.json (list of recorded notices, optional)
A source counts as "checked" when its fixture is present (RW always is),
so NONE cases need a committed — possibly empty — Crossref fixture to reach
NONE/HIGH rather than UNKNOWN.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from citeguard.crossref import crossref_signals
from citeguard.openalex import openalex_signal
from citeguard.retractionwatch import (
    HijackedIndex,
    RWIndex,
    hijacked_signal,
    load_dump,
    load_hijacked,
    rw_signals,
)
from citeguard.status import (
    EditorialStatus,
    Signal,
    Source,
    StatusKind,
    normalize_doi,
    resolve,
)

EVALS = Path(__file__).parent
FIXTURES = EVALS / "fixtures"


def slug(doi: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", doi.lower()).strip("_")


@dataclass(frozen=True)
class GoldCase:
    doi: str
    expected_kind: str
    must_not_be: tuple[str, ...]
    min_confidence: str | None
    tags: tuple[str, ...]
    rationale: str


def load_gold(path: Path) -> list[GoldCase]:
    cases = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        d = json.loads(line)
        cases.append(
            GoldCase(
                doi=normalize_doi(d["doi"]) or d["doi"].lower(),
                expected_kind=d["expected_kind"],
                must_not_be=tuple(d.get("must_not_be", [])),
                min_confidence=d.get("min_confidence"),
                tags=tuple(d.get("tags", [])),
                rationale=d.get("rationale", ""),
            )
        )
    return cases


def _venue(work: dict[str, Any]) -> tuple[str | None, str | None]:
    source = (work.get("primary_location") or {}).get("source") or {}
    issns = source.get("issn") or []
    return source.get("display_name"), issns[0] if issns else None


def resolve_gold_case(
    doi: str, rw_index: RWIndex, hijacked: HijackedIndex | None
) -> EditorialStatus:
    signals: list[Signal] = list(rw_signals(rw_index.get(doi, [])))
    checked: set[Source] = {Source.RETRACTION_WATCH}

    oa_file = FIXTURES / "openalex" / f"{slug(doi)}.json"
    if oa_file.exists():
        work = json.loads(oa_file.read_text())
        checked.add(Source.OPENALEX)
        if sig := openalex_signal(work):
            signals.append(sig)
        if hijacked is not None:
            journal, issn = _venue(work)
            if hsig := hijacked_signal(journal, issn, hijacked):
                signals.append(hsig)

    cr_file = FIXTURES / "crossref" / f"{slug(doi)}.json"
    if cr_file.exists():
        notices = json.loads(cr_file.read_text())
        checked.add(Source.CROSSREF)
        signals.extend(crossref_signals(notices, doi))

    return resolve(doi, signals, frozenset(checked))


_CONF_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class CaseResult:
    case: GoldCase
    predicted: StatusKind
    confidence: str
    ok: bool
    violations: list[str]


def evaluate(
    gold: list[GoldCase], rw_index: RWIndex, hijacked: HijackedIndex | None
) -> list[CaseResult]:
    results = []
    for case in gold:
        status = resolve_gold_case(case.doi, rw_index, hijacked)
        violations: list[str] = []
        if status.kind.value != case.expected_kind:
            violations.append(f"expected {case.expected_kind}, got {status.kind.value}")
        if status.kind.value in case.must_not_be:
            violations.append(f"MUST-NOT-BE violated: predicted {status.kind.value}")
        if (
            case.min_confidence
            and _CONF_RANK[status.confidence.value] < _CONF_RANK[case.min_confidence]
        ):
            violations.append(
                f"confidence {status.confidence.value} below required {case.min_confidence}"
            )
        results.append(
            CaseResult(
                case=case,
                predicted=status.kind,
                confidence=status.confidence.value,
                ok=not violations,
                violations=violations,
            )
        )
    return results


def load_fixtures() -> tuple[RWIndex, HijackedIndex | None]:
    rw_index = load_dump(FIXTURES / "rw_gold.csv")
    hijacked_csv = FIXTURES / "hijacked_gold.csv"
    hijacked = load_hijacked(hijacked_csv) if hijacked_csv.exists() else None
    return rw_index, hijacked
