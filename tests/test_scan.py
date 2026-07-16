"""Contamination-scan tests: local join over fake works (no network)."""

import json
from pathlib import Path

from citeguard.retractionwatch import RWIndex
from citeguard.scan import scan_works
from citeguard.watch import load_reverse_flagged_map
from tests.conftest import openalex_work


def test_scan_counts_flagged_citations(rw_index: RWIndex) -> None:
    # flagged papers in rw_mini: paper.1 (retracted), paper.3 (EoC)
    retracted = openalex_work("10.9999/paper.1")
    eoc = openalex_work("10.9999/paper.3")
    clean = openalex_work("10.9999/clean.1")
    flagged_id_to_doi = {retracted["id"]: "10.9999/paper.1", eoc["id"]: "10.9999/paper.3"}

    citing_both = openalex_work(
        "10.9999/w1", referenced_works=[retracted["id"], eoc["id"], clean["id"]]
    )
    citing_one = openalex_work("10.9999/w2", referenced_works=[retracted["id"]])
    citing_none = openalex_work("10.9999/w3", referenced_works=[clean["id"]])
    no_refs = openalex_work("10.9999/w4", referenced_works=[])

    report = scan_works(
        [citing_both, citing_one, citing_none, no_refs],
        rw_index,
        flagged_id_to_doi,
        corpus="test-corpus",
    )

    assert report.works_scanned == 4
    assert report.works_with_references == 3
    assert report.works_with_flagged_refs == 2  # w1 and w2
    assert report.total_flagged_citations == 3  # w1: 2, w2: 1
    assert report.by_kind == {"retracted": 2, "expression_of_concern": 1}
    assert report.contamination_rate == 2 / 3
    # paper.1 cited twice -> top of most_cited
    assert report.most_cited_flagged[0] == ("10.9999/paper.1", "retracted", 2)
    # worst work is w1 (2 flagged refs)
    assert report.worst_works[0].doi == "10.9999/w1"
    assert len(report.worst_works[0].flagged_refs) == 2


def test_scan_report_serializes(rw_index: RWIndex) -> None:
    r = openalex_work("10.9999/paper.1")
    report = scan_works(
        [openalex_work("10.9999/w1", referenced_works=[r["id"]])],
        rw_index,
        {r["id"]: "10.9999/paper.1"},
        corpus="c",
    )
    payload = json.dumps(report.to_dict())
    assert json.loads(payload)["contamination_rate"] == 1.0
    md = report.to_markdown()
    assert "Citation contamination scan" in md
    assert "retracted" in md


def test_empty_flagged_map_finds_nothing(rw_index: RWIndex) -> None:
    report = scan_works(
        [openalex_work("10.9999/w1", referenced_works=["https://openalex.org/W999"])],
        rw_index,
        {},
        corpus="c",
    )
    assert report.works_with_flagged_refs == 0
    assert report.total_flagged_citations == 0


def test_scan_scores_citation_timing(rw_index: RWIndex) -> None:
    # rw_mini: 10.9999/paper.1 was retracted 2020-01-15.
    retracted = openalex_work("10.9999/paper.1")
    flagged_id_to_doi = {retracted["id"]: "10.9999/paper.1"}

    before = openalex_work("10.9999/before", referenced_works=[retracted["id"]])
    before["publication_date"] = "2018-06-01"  # cited before the notice
    after = openalex_work("10.9999/after", referenced_works=[retracted["id"]])
    after["publication_date"] = "2023-06-01"  # cited years after

    report = scan_works([before, after], rw_index, flagged_id_to_doi, corpus="c")

    assert report.by_timing == {"pre_notice": 1, "post_notice": 1}
    assert report.post_notice_citations == 1
    # the "after" work's flagged ref is scored post-notice with a positive gap
    after_work = next(w for w in report.worst_works if w.doi == "10.9999/after")
    ref = after_work.flagged_refs[0]
    assert ref.timing == "post_notice"
    assert ref.gap_years is not None and ref.gap_years > 3
    # serialization carries timing through
    payload = json.loads(json.dumps(report.to_dict()))
    assert payload["post_notice_citations"] == 1
    assert payload["by_timing"]["post_notice"] == 1
    assert "Post-notice citations" in report.to_markdown()


def test_load_reverse_flagged_map(tmp_path: Path) -> None:
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"10.1/a": "https://openalex.org/W1", "10.1/b": None}))
    rev = load_reverse_flagged_map(p)
    assert rev == {"https://openalex.org/W1": "10.1/a"}
    assert load_reverse_flagged_map(tmp_path / "missing.json") == {}
