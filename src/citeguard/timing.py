"""Score a citation by *when* it was made relative to the editorial notice.

Pure module, no I/O. A citation to a retracted paper is not all the same:
citing it *before* the retraction notice existed is blameless; citing it
years *after* is the thing that matters. A grace window absorbs the time a
notice takes to propagate through indexing and awareness, so a citation days
after the notice isn't scored as if the author should already have known.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

# ponytail: default 365d propagation grace; tune per study if you have evidence
# on how fast retraction awareness spreads in a given field.
DEFAULT_GRACE_DAYS = 365


class CitationTiming(StrEnum):
    PRE_NOTICE = "pre_notice"  # cited before the notice existed (blameless)
    CONCURRENT = "concurrent"  # within the grace window after the notice
    POST_NOTICE = "post_notice"  # cited well after the notice (should have known)
    UNKNOWN = "unknown"  # a date is missing


def _parse(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def classify_citation_timing(
    citing_publication_date: str | date | None,
    notice_date: str | date | None,
    grace_days: int = DEFAULT_GRACE_DAYS,
) -> tuple[CitationTiming, float | None]:
    """Return (timing, gap_years).

    gap_years is signed: negative = cited before the notice, positive = after.
    None when either date is unavailable.
    """
    citing = _parse(citing_publication_date)
    notice = _parse(notice_date)
    if citing is None or notice is None:
        return CitationTiming.UNKNOWN, None

    gap_days = (citing - notice).days
    gap_years = round(gap_days / 365.25, 2)
    if gap_days < 0:
        return CitationTiming.PRE_NOTICE, gap_years
    if gap_days <= grace_days:
        return CitationTiming.CONCURRENT, gap_years
    return CitationTiming.POST_NOTICE, gap_years
