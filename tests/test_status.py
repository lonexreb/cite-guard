"""Unit tests for the pure resolution core (rules R1-R6)."""

from datetime import date

import pytest

from citeguard.status import (
    Confidence,
    Signal,
    Source,
    StatusKind,
    Strength,
    normalize_doi,
    resolve,
)

ALL = frozenset({Source.RETRACTION_WATCH, Source.OPENALEX, Source.CROSSREF})
DOI = "10.1000/example"


def rw(kind: StatusKind, d: date | None = None, url: str | None = None) -> Signal:
    return Signal(
        source=Source.RETRACTION_WATCH,
        kind=kind,
        strength=Strength.STRONG,
        date=d,
        evidence_url=url,
    )


def cr(kind: StatusKind, d: date | None = None) -> Signal:
    return Signal(source=Source.CROSSREF, kind=kind, strength=Strength.STRONG, date=d)


def oa_retracted() -> Signal:
    return Signal(source=Source.OPENALEX, kind=StatusKind.RETRACTED, strength=Strength.WEAK)


def hijacked(hint: Confidence = Confidence.HIGH) -> Signal:
    return Signal(
        source=Source.RETRACTION_WATCH,
        kind=StatusKind.HIJACKED_JOURNAL,
        strength=Strength.STRONG,
        confidence_hint=hint,
        detail="issn-match",
    )


# ---------------------------------------------------------------- normalize_doi


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1000/ABC", "10.1000/abc"),
        ("https://doi.org/10.1000/abc", "10.1000/abc"),
        ("http://dx.doi.org/10.1000/Abc", "10.1000/abc"),
        ("doi:10.1000/abc", "10.1000/abc"),
        ("  10.1000/abc  ", "10.1000/abc"),
        ("not-a-doi", None),
        ("11.1000/abc", None),
        ("10.1000", None),
        ("", None),
    ],
)
def test_normalize_doi(raw: str, expected: str | None) -> None:
    assert normalize_doi(raw) == expected


def test_normalize_doi_idempotent() -> None:
    once = normalize_doi("https://doi.org/10.1000/ABC")
    assert once is not None
    assert normalize_doi(once) == once


# ------------------------------------------------------------------ R1 timeline


def test_r1_single_retraction() -> None:
    s = resolve(DOI, [rw(StatusKind.RETRACTED, date(2020, 1, 1), "https://ev")], ALL)
    assert s.kind is StatusKind.RETRACTED
    assert s.confidence is Confidence.HIGH
    assert s.evidence_url == "https://ev"
    assert s.date == date(2020, 1, 1)


def test_r1_eoc_then_retraction_escalates() -> None:
    s = resolve(
        DOI,
        [
            rw(StatusKind.EXPRESSION_OF_CONCERN, date(2019, 1, 1)),
            rw(StatusKind.RETRACTED, date(2020, 1, 1)),
        ],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED
    assert any("Escalated" in n for n in s.notes)


def test_r1_retraction_then_reinstatement_downgrades_with_history() -> None:
    s = resolve(
        DOI,
        [
            rw(StatusKind.RETRACTED, date(2019, 1, 1)),
            rw(StatusKind.REINSTATED, date(2021, 1, 1)),
        ],
        ALL,
    )
    assert s.kind is StatusKind.REINSTATED
    assert any("Previously retracted" in n for n in s.notes)


def test_r1_reinstatement_before_later_retraction_is_superseded() -> None:
    s = resolve(
        DOI,
        [
            rw(StatusKind.REINSTATED, date(2019, 1, 1)),
            rw(StatusKind.RETRACTED, date(2020, 1, 1)),
        ],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED


def test_r1_correction_does_not_downgrade_retraction() -> None:
    s = resolve(
        DOI,
        [
            rw(StatusKind.RETRACTED, date(2019, 1, 1)),
            rw(StatusKind.CORRECTED, date(2020, 1, 1)),
        ],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED


def test_r1_eoc_not_overridden_by_correction() -> None:
    s = resolve(
        DOI,
        [
            rw(StatusKind.EXPRESSION_OF_CONCERN, date(2019, 1, 1)),
            rw(StatusKind.CORRECTED, date(2020, 1, 1)),
        ],
        ALL,
    )
    assert s.kind is StatusKind.EXPRESSION_OF_CONCERN


def test_r1_undated_records_noted() -> None:
    s = resolve(
        DOI,
        [rw(StatusKind.RETRACTED, date(2020, 1, 1)), rw(StatusKind.CORRECTED, None)],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED
    assert any("parseable date" in n for n in s.notes)


# --------------------------------------------------------------------- R2 merge


def test_r2_rw_and_crossref_agree_high_confidence() -> None:
    s = resolve(
        DOI,
        [rw(StatusKind.RETRACTED, date(2020, 1, 1)), cr(StatusKind.RETRACTED)],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED
    assert s.confidence is Confidence.HIGH
    assert not s.conflict


def test_r2_disagreement_takes_more_severe_and_flags_conflict() -> None:
    s = resolve(
        DOI,
        [rw(StatusKind.RETRACTED, date(2020, 1, 1)), cr(StatusKind.CORRECTED)],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED
    assert s.conflict
    assert s.confidence is Confidence.MEDIUM
    assert any("disagree" in n.lower() for n in s.notes)


def test_r2_crossref_eoc_beats_rw_correction_severity() -> None:
    s = resolve(
        DOI,
        [rw(StatusKind.CORRECTED, date(2020, 1, 1)), cr(StatusKind.EXPRESSION_OF_CONCERN)],
        ALL,
    )
    assert s.kind is StatusKind.EXPRESSION_OF_CONCERN
    assert s.conflict


def test_r2_reinstatement_is_not_a_conflict_with_stale_crossref_notice() -> None:
    s = resolve(
        DOI,
        [
            rw(StatusKind.RETRACTED, date(2019, 1, 1)),
            rw(StatusKind.REINSTATED, date(2021, 1, 1)),
            cr(StatusKind.RETRACTED),
        ],
        ALL,
    )
    assert s.kind is StatusKind.REINSTATED
    assert not s.conflict
    assert any("later reinstatement" in n for n in s.notes)


def test_r2_crossref_only_notice_is_sufficient() -> None:
    s = resolve(DOI, [cr(StatusKind.RETRACTED, date(2022, 5, 1))], ALL)
    assert s.kind is StatusKind.RETRACTED
    assert s.confidence is Confidence.HIGH


# ------------------------------------------------------------ R3 the invariant


def test_r3_openalex_alone_never_yields_retracted() -> None:
    s = resolve(DOI, [oa_retracted()], ALL)
    assert s.kind is StatusKind.UNKNOWN
    assert s.confidence is Confidence.LOW
    assert any("false positives" in n for n in s.notes)


def test_r3_openalex_plus_strong_signal_is_fine() -> None:
    s = resolve(DOI, [oa_retracted(), rw(StatusKind.RETRACTED, date(2020, 1, 1))], ALL)
    assert s.kind is StatusKind.RETRACTED
    assert s.confidence is Confidence.HIGH


# ------------------------------------------------------------------- R4 oa lag


def test_r4_strong_retraction_with_openalex_silent_notes_lag() -> None:
    s = resolve(DOI, [rw(StatusKind.RETRACTED, date(2020, 1, 1))], ALL)
    assert s.kind is StatusKind.RETRACTED
    assert not s.conflict
    assert any("does not (yet) flag" in n for n in s.notes)


# ------------------------------------------------------------------ R5 hijacked


def test_r5_hijacked_venue_flags_clean_article() -> None:
    s = resolve(DOI, [hijacked(Confidence.HIGH)], ALL)
    assert s.kind is StatusKind.HIJACKED_JOURNAL
    assert s.confidence is Confidence.HIGH
    assert any("not the" in n and "authors" in n for n in s.notes)


def test_r5_title_only_match_is_medium_confidence() -> None:
    s = resolve(DOI, [hijacked(Confidence.MEDIUM)], ALL)
    assert s.confidence is Confidence.MEDIUM


def test_r5_article_level_status_outranks_hijacked_venue() -> None:
    s = resolve(
        DOI,
        [rw(StatusKind.RETRACTED, date(2020, 1, 1)), hijacked()],
        ALL,
    )
    assert s.kind is StatusKind.RETRACTED
    assert any("hijacked-journal list" in n for n in s.notes)


# ------------------------------------------------------------- R6 none/unknown


def test_r6_all_checked_and_clean_is_none_high() -> None:
    s = resolve(DOI, [], ALL)
    assert s.kind is StatusKind.NONE
    assert s.confidence is Confidence.HIGH


def test_r6_partial_strong_coverage_is_none_medium() -> None:
    s = resolve(DOI, [], frozenset({Source.RETRACTION_WATCH, Source.OPENALEX}))
    assert s.kind is StatusKind.NONE
    assert s.confidence is Confidence.MEDIUM
    assert any("crossref" in n for n in s.notes)


def test_r6_only_openalex_checked_is_unknown() -> None:
    s = resolve(DOI, [], frozenset({Source.OPENALEX}))
    assert s.kind is StatusKind.UNKNOWN
    assert s.confidence is Confidence.LOW


# ------------------------------------------------------------- serialization


def test_to_dict_is_json_safe() -> None:
    import json

    s = resolve(DOI, [rw(StatusKind.RETRACTED, date(2020, 1, 1), "https://ev")], ALL)
    payload = json.dumps(s.to_dict())
    round_tripped = json.loads(payload)
    assert round_tripped["kind"] == "retracted"
    assert round_tripped["date"] == "2020-01-01"
    assert round_tripped["sources_checked"] == ["crossref", "openalex", "retraction_watch"]
