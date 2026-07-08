"""Crossref helpers: update-to mapping and notice discovery (no network)."""

from datetime import date
from pathlib import Path

import httpx

from citeguard.crossref import CrossrefClient, crossref_signals
from citeguard.status import StatusKind

TARGET = "10.1/target"


def notice(update_type: str, notice_doi: str = "10.1/notice") -> dict:
    return {
        "DOI": notice_doi,
        "update-to": [
            {"DOI": TARGET, "type": update_type, "updated": {"date-parts": [[2021, 6, 3]]}}
        ],
    }


def test_type_mapping() -> None:
    cases = {
        "retraction": StatusKind.RETRACTED,
        "withdrawal": StatusKind.RETRACTED,
        "removal": StatusKind.RETRACTED,
        "erratum": StatusKind.CORRECTED,
        "corrigendum": StatusKind.CORRECTED,
        "correction": StatusKind.CORRECTED,
        "partial_retraction": StatusKind.CORRECTED,
        "expression_of_concern": StatusKind.EXPRESSION_OF_CONCERN,
    }
    for raw, kind in cases.items():
        (sig,) = crossref_signals([notice(raw)], TARGET)
        assert sig.kind is kind, raw
        assert sig.date == date(2021, 6, 3)
        assert sig.evidence_url == "https://doi.org/10.1/notice"


def test_new_version_is_not_an_editorial_flag() -> None:
    assert crossref_signals([notice("new_version")], TARGET) == []


def test_update_to_other_doi_ignored() -> None:
    n = notice("retraction")
    n["update-to"][0]["DOI"] = "10.1/someone-else"
    assert crossref_signals([n], TARGET) == []


def test_hyphenated_type_normalized() -> None:
    (sig,) = crossref_signals([notice("Expression-of-Concern")], TARGET)
    assert sig.kind is StatusKind.EXPRESSION_OF_CONCERN


def test_get_updates_for_queries_updates_filter(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"message": {"items": [notice("retraction")]}})

    client = CrossrefClient(
        mailto="m@example.org",
        transport=httpx.MockTransport(handler),
        cache_dir=tmp_path / "cache",
    )
    items = client.get_updates_for(f"https://doi.org/{TARGET}")
    assert len(items) == 1
    assert "filter=updates%3A10.1%2Ftarget" in seen[0]
    # cached on second call
    client.get_updates_for(TARGET)
    assert len(seen) == 1


def test_invalid_doi_returns_empty_without_request(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not be called")

    client = CrossrefClient(transport=httpx.MockTransport(handler), cache_dir=None)
    assert client.get_updates_for("not-a-doi") == []
