"""Checker tests: bib extraction and end-to-end DOI resolution with fakes."""

from pathlib import Path

from citeguard.checker import check_bibtex, check_dois, check_paper, extract_dois_from_bib
from citeguard.retractionwatch import RWIndex
from citeguard.status import StatusKind
from tests.conftest import FakeOpenAlexHandler, make_cr_client, make_oa_client, openalex_work

FIXTURES = Path(__file__).parent / "fixtures"
BIB = (FIXTURES / "refs_mini.bib").read_text()


def test_extract_dois_from_bib() -> None:
    keyed = dict(extract_dois_from_bib(BIB))
    assert keyed["has_doi_field"] == "10.9999/paper.1"
    assert keyed["doi_in_url"] == "10.9999/paper.2"
    assert keyed["no_doi_at_all"] is None
    assert keyed["clean_paper"] == "10.9999/clean.1"


def test_check_dois_rw_only_local_join(rw_index: RWIndex) -> None:
    retracted, clean = check_dois(
        ["10.9999/paper.1", "10.9999/clean.1"], rw_index=rw_index
    )
    assert retracted.kind is StatusKind.RETRACTED
    # RW only: strong coverage is partial -> NONE at reduced confidence
    assert clean.kind is StatusKind.NONE
    assert clean.confidence.value == "medium"


def test_check_dois_full_stack(rw_index: RWIndex) -> None:
    oa = make_oa_client(
        FakeOpenAlexHandler(
            [openalex_work("10.9999/paper.1", retracted=True), openalex_work("10.9999/clean.1")]
        )
    )
    cr = make_cr_client(
        {
            "10.9999/paper.1": [
                {
                    "DOI": "10.9999/notice.1",
                    "update-to": [
                        {
                            "DOI": "10.9999/paper.1",
                            "type": "retraction",
                            "updated": {"date-parts": [[2020, 1, 15]]},
                        }
                    ],
                }
            ]
        }
    )
    retracted, clean = check_dois(
        ["10.9999/paper.1", "10.9999/clean.1"], rw_index=rw_index, oa_client=oa, cr_client=cr
    )
    assert retracted.kind is StatusKind.RETRACTED
    assert retracted.confidence.value == "high"
    assert not retracted.conflict
    assert len(retracted.sources_checked) == 3
    assert clean.kind is StatusKind.NONE
    assert clean.confidence.value == "high"  # all sources consulted


def test_invalid_doi_is_unknown_with_note(rw_index: RWIndex) -> None:
    (status,) = check_dois(["garbage"], rw_index=rw_index)
    assert status.kind is StatusKind.UNKNOWN
    assert any("Not a recognizable DOI" in n for n in status.notes)


def test_check_bibtex_maps_entries(rw_index: RWIndex) -> None:
    results = {r.ref: r.status for r in check_bibtex(BIB, rw_index=rw_index)}
    assert results["has_doi_field"].kind is StatusKind.RETRACTED
    assert results["no_doi_at_all"].kind is StatusKind.UNKNOWN
    assert results["doi_in_url"].kind is StatusKind.CORRECTED


def test_check_paper_checks_paper_and_references(rw_index: RWIndex) -> None:
    flagged_ref = openalex_work("10.9999/paper.1", retracted=True)
    clean_ref = openalex_work("10.9999/clean.1")
    paper = openalex_work(
        "10.9999/citing.1", referenced_works=[flagged_ref["id"], clean_ref["id"]]
    )
    oa = make_oa_client(FakeOpenAlexHandler([paper, flagged_ref, clean_ref]))
    report = check_paper("10.9999/citing.1", rw_index=rw_index, oa_client=oa)
    assert report is not None
    assert report.paper.kind is StatusKind.NONE
    by_ref = {r.ref: r.status.kind for r in report.references}
    assert by_ref[flagged_ref["id"]] is StatusKind.RETRACTED
    assert by_ref[clean_ref["id"]] is StatusKind.NONE
    assert report.references_without_doi == 0


def test_check_paper_unknown_doi_returns_none(rw_index: RWIndex) -> None:
    oa = make_oa_client(FakeOpenAlexHandler([]))
    assert check_paper("10.9999/nope", rw_index=rw_index, oa_client=oa) is None


def test_hijacked_venue_flagged_via_openalex_metadata(rw_index, hijacked_index) -> None:
    work = openalex_work("10.9999/clean.2", journal="Journal of Hijacked Studies", issn="1234-5678")
    oa = make_oa_client(FakeOpenAlexHandler([work]))
    (status,) = check_dois(
        ["10.9999/clean.2"], rw_index=rw_index, oa_client=oa, hijacked=hijacked_index
    )
    assert status.kind is StatusKind.HIJACKED_JOURNAL
    assert status.confidence.value == "high"
