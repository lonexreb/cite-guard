"""Ingest and normalize the Retraction Watch dataset (distributed by Crossref).

Data: https://gitlab.com/crossref/retraction-watch-data (updated daily).
Attribution: Retraction Watch / The Center for Scientific Integrity, made
publicly available by Crossref.

The optional hijacked-journal list is *separate* from the CSV (Retraction
Watch's Hijacked Journal Checker); if a local copy is provided we use it,
otherwise HIJACKED_JOURNAL stays model-supported but data-pending.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx

from citeguard.status import Confidence, Signal, Source, StatusKind, Strength, normalize_doi

RW_DUMP_URL = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"

_NATURE_MAP: dict[str, StatusKind] = {
    "retraction": StatusKind.RETRACTED,
    "correction": StatusKind.CORRECTED,
    "expression of concern": StatusKind.EXPRESSION_OF_CONCERN,
    "reinstatement": StatusKind.REINSTATED,
}

_DATE_FORMATS = ("%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d")


@dataclass(frozen=True, slots=True)
class RWRecord:
    record_id: str
    original_doi: str  # normalized
    nature: StatusKind
    retraction_date: date | None
    notice_doi: str | None
    journal: str
    publisher: str
    reason: str
    urls: str


# original DOI (normalized) -> all RW records for it, unordered
RWIndex = dict[str, list[RWRecord]]


def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def download_dump(dest: Path, url: str = RW_DUMP_URL, timeout: float = 120.0) -> Path:
    """Stream the daily CSV to disk. Free (GitLab); no API credits involved."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)
    tmp.replace(dest)
    return dest


def load_dump(path: Path) -> RWIndex:
    """Parse the CSV into an index keyed by normalized original-paper DOI.

    Rows with a missing/invalid original DOI or an unrecognized
    RetractionNature are skipped (conservative: we never guess).
    """
    index: RWIndex = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            doi = normalize_doi(row.get("OriginalPaperDOI") or "")
            nature = _NATURE_MAP.get((row.get("RetractionNature") or "").strip().lower())
            if doi is None or nature is None:
                continue
            notice_doi = normalize_doi(row.get("RetractionDOI") or "")
            record = RWRecord(
                record_id=(row.get("Record ID") or "").strip(),
                original_doi=doi,
                nature=nature,
                retraction_date=_parse_date(row.get("RetractionDate") or ""),
                notice_doi=notice_doi,
                journal=(row.get("Journal") or "").strip(),
                publisher=(row.get("Publisher") or "").strip(),
                reason=(row.get("Reason") or "").strip(),
                urls=(row.get("URLS") or "").strip(),
            )
            index.setdefault(doi, []).append(record)
    return index


def rw_signals(records: list[RWRecord]) -> list[Signal]:
    """One STRONG signal per RW record; resolve() collapses the timeline."""
    signals = []
    for r in records:
        evidence = f"https://doi.org/{r.notice_doi}" if r.notice_doi else (r.urls or None)
        signals.append(
            Signal(
                source=Source.RETRACTION_WATCH,
                kind=r.nature,
                strength=Strength.STRONG,
                date=r.retraction_date,
                notice_doi=r.notice_doi,
                evidence_url=evidence,
                detail=r.reason,
            )
        )
    return signals


# --------------------------------------------------------- hijacked journals


@dataclass(frozen=True, slots=True)
class HijackedIndex:
    issns: frozenset[str]
    titles: frozenset[str]  # lowercase


def load_hijacked(path: Path) -> HijackedIndex:
    """Optional local CSV with at least Title and/or ISSN columns."""
    issns: set[str] = set()
    titles: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            issn = (row.get("ISSN") or "").strip()
            title = (row.get("Title") or "").strip().lower()
            if issn:
                issns.add(issn)
            if title:
                titles.add(title)
    return HijackedIndex(issns=frozenset(issns), titles=frozenset(titles))


def hijacked_signal(
    journal: str | None, issn: str | None, index: HijackedIndex
) -> Signal | None:
    """Venue-level signal. ISSN match is HIGH; title-only match is MEDIUM
    (title collisions with legitimate journals are exactly how hijacking works)."""
    if issn and issn.strip() in index.issns:
        return Signal(
            source=Source.RETRACTION_WATCH,
            kind=StatusKind.HIJACKED_JOURNAL,
            strength=Strength.STRONG,
            detail=f"ISSN {issn} on hijacked-journal list",
            confidence_hint=Confidence.HIGH,
        )
    if journal and journal.strip().lower() in index.titles:
        return Signal(
            source=Source.RETRACTION_WATCH,
            kind=StatusKind.HIJACKED_JOURNAL,
            strength=Strength.STRONG,
            detail=f"journal title '{journal}' on hijacked-journal list (title-only match)",
            confidence_hint=Confidence.MEDIUM,
        )
    return None
