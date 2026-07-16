"""Unit tests for citation-timing classification (pure, no I/O)."""

from datetime import date

import pytest

from citeguard.timing import CitationTiming, classify_citation_timing

NOTICE = date(2020, 1, 15)


@pytest.mark.parametrize(
    ("citing", "expected"),
    [
        ("2018-06-01", CitationTiming.PRE_NOTICE),  # cited before the notice
        ("2020-01-14", CitationTiming.PRE_NOTICE),  # day before
        ("2020-01-15", CitationTiming.CONCURRENT),  # same day -> grace window
        ("2020-06-01", CitationTiming.CONCURRENT),  # within 365d
        ("2021-06-01", CitationTiming.POST_NOTICE),  # well after
        ("2024-01-01", CitationTiming.POST_NOTICE),
    ],
)
def test_classification(citing: str, expected: CitationTiming) -> None:
    timing, gap = classify_citation_timing(citing, NOTICE)
    assert timing is expected
    assert gap is not None


def test_gap_years_sign() -> None:
    _, before = classify_citation_timing("2018-01-15", NOTICE)
    _, after = classify_citation_timing("2022-01-15", NOTICE)
    assert before is not None and before < 0
    assert after is not None and after > 0


def test_missing_dates_are_unknown() -> None:
    assert classify_citation_timing(None, NOTICE) == (CitationTiming.UNKNOWN, None)
    assert classify_citation_timing("2020-01-01", None) == (CitationTiming.UNKNOWN, None)


def test_partial_citing_date_parses() -> None:
    timing, _ = classify_citation_timing("2024", NOTICE)  # year only
    assert timing is CitationTiming.POST_NOTICE


def test_grace_window_is_configurable() -> None:
    # with zero grace, the day after the notice is already post-notice
    timing, _ = classify_citation_timing("2020-02-01", NOTICE, grace_days=0)
    assert timing is CitationTiming.POST_NOTICE
