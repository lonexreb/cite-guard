"""Tests for RW dump parsing and signal emission (offline fixture)."""

from datetime import date
from pathlib import Path

import pytest

from citeguard.retractionwatch import (
    HijackedIndex,
    RWIndex,
    hijacked_signal,
    load_dump,
    load_hijacked,
    rw_signals,
)
from citeguard.status import ALL_SOURCES

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def index() -> RWIndex:
    return load_dump(FIXTURES / "rw_mini.csv")


def test_rows_without_valid_doi_or_known_nature_are_skipped(index: RWIndex) -> None:
    assert "10.9999/paper.8" not in index  # unknown RetractionNature
    # row 9 has OriginalPaperDOI "unavailable" -> not a DOI -> skipped
    assert all(doi.startswith("10.") for doi in index)
    assert len(index) == 8


def test_multi_record_doi_grouped(index: RWIndex) -> None:
    records = index["10.9999/paper.4"]
    assert len(records) == 2
    assert {r.nature.value for r in records} == {"expression_of_concern", "retracted"}


def test_dates_and_dois_normalized(index: RWIndex) -> None:
    (rec,) = index["10.9999/paper.1"]
    assert rec.retraction_date == date(2020, 1, 15)
    assert rec.notice_doi == "10.9999/notice.1"
    (upper,) = index["10.9999/paper.7"]  # uppercase in CSV
    assert upper.notice_doi == "10.9999/notice.7"


def test_unparseable_date_becomes_none(index: RWIndex) -> None:
    (rec,) = index["10.9999/paper.6"]
    assert rec.retraction_date is None


def test_signals_prefer_notice_doi_url_then_urls_field(index: RWIndex) -> None:
    (sig,) = rw_signals(index["10.9999/paper.1"])
    assert sig.evidence_url == "https://doi.org/10.9999/notice.1"
    (sig9,) = rw_signals(index["10.9999/paper.9"])  # notice DOI "unavailable"
    assert sig9.notice_doi is None
    assert sig9.evidence_url == "https://example.org/notice"


def test_reinstatement_timeline_resolves_via_status(index: RWIndex) -> None:
    from citeguard.status import StatusKind, resolve

    s = resolve("10.9999/paper.5", rw_signals(index["10.9999/paper.5"]), ALL_SOURCES)
    assert s.kind is StatusKind.REINSTATED


# --------------------------------------------------------- hijacked journals


@pytest.fixture(scope="module")
def hidx() -> HijackedIndex:
    return load_hijacked(FIXTURES / "hijacked_mini.csv")


def test_hijacked_issn_match_is_high(hidx: HijackedIndex) -> None:
    sig = hijacked_signal("Anything", "1234-5678", hidx)
    assert sig is not None
    assert sig.confidence_hint is not None and sig.confidence_hint.value == "high"


def test_hijacked_title_only_match_is_medium(hidx: HijackedIndex) -> None:
    sig = hijacked_signal("Cloned Review Letters", None, hidx)
    assert sig is not None
    assert sig.confidence_hint is not None and sig.confidence_hint.value == "medium"


def test_hijacked_no_match(hidx: HijackedIndex) -> None:
    assert hijacked_signal("Legit Journal", "9999-0000", hidx) is None
