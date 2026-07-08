"""Shared fixtures: mini RW index, fake OpenAlex/Crossref clients."""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from citeguard.crossref import CrossrefClient
from citeguard.openalex import OpenAlexClient
from citeguard.retractionwatch import HijackedIndex, RWIndex, load_dump, load_hijacked

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def rw_index() -> RWIndex:
    return load_dump(FIXTURES / "rw_mini.csv")


@pytest.fixture(scope="session")
def hijacked_index() -> HijackedIndex:
    return load_hijacked(FIXTURES / "hijacked_mini.csv")


def openalex_work(
    doi: str,
    retracted: bool = False,
    referenced_works: list[str] | None = None,
    journal: str | None = None,
    issn: str | None = None,
) -> dict:
    return {
        "id": f"https://openalex.org/W{abs(hash(doi)) % 10**8}",
        "doi": f"https://doi.org/{doi}",
        "title": f"Work {doi}",
        "publication_date": "2020-01-01",
        "is_retracted": retracted,
        "is_paratext": False,
        "referenced_works": referenced_works or [],
        "primary_location": {
            "source": {"display_name": journal, "issn": [issn] if issn else []}
        },
    }


class FakeOpenAlexHandler:
    """Serves a fixed corpus of works for both DOI-batch and ID-batch filters."""

    def __init__(self, works: list[dict]) -> None:
        self.by_doi = {w["doi"].removeprefix("https://doi.org/"): w for w in works}
        self.by_id = {w["id"]: w for w in works}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.startswith("/works/"):
            ident = path.removeprefix("/works/").removeprefix("https://doi.org/")
            work = self.by_doi.get(ident)
            if work is None:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=work)
        qs = parse_qs(urlparse(str(request.url)).query)
        filt = qs.get("filter", [""])[0]
        results: list[dict] = []
        if filt.startswith("doi:"):
            results = [
                self.by_doi[d] for d in filt.removeprefix("doi:").split("|") if d in self.by_doi
            ]
        elif filt.startswith("ids.openalex:"):
            for short in filt.removeprefix("ids.openalex:").split("|"):
                full = f"https://openalex.org/{short}"
                if full in self.by_id:
                    results.append(self.by_id[full])
        return httpx.Response(200, json={"results": results, "meta": {}})


def make_oa_client(handler: FakeOpenAlexHandler, cache_dir: Path | None = None) -> OpenAlexClient:
    return OpenAlexClient(
        api_key="test-key",
        mailto="test@example.org",
        transport=httpx.MockTransport(handler),
        cache_dir=cache_dir,
        retry_base_seconds=0.0,
    )


class FakeCrossrefHandler:
    """Serves canned update-to notices keyed by target DOI."""

    def __init__(self, notices_by_doi: dict[str, list[dict]]) -> None:
        self.notices_by_doi = notices_by_doi

    def __call__(self, request: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(request.url)).query)
        filt = qs.get("filter", [""])[0]
        doi = filt.removeprefix("updates:")
        return httpx.Response(
            200, json={"message": {"items": self.notices_by_doi.get(doi, [])}}
        )


def make_cr_client(notices_by_doi: dict[str, list[dict]]) -> CrossrefClient:
    return CrossrefClient(
        mailto="test@example.org",
        transport=httpx.MockTransport(FakeCrossrefHandler(notices_by_doi)),
        cache_dir=None,
        retry_base_seconds=0.0,
    )
