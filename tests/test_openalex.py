"""OpenAlex client tests: MockTransport, no network."""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from citeguard.openalex import OpenAlexClient, openalex_signal, paratext_note
from citeguard.status import StatusKind, Strength


def make_work(doi: str, retracted: bool = False) -> dict:
    return {
        "id": f"https://openalex.org/W{abs(hash(doi)) % 10**8}",
        "doi": f"https://doi.org/{doi}",
        "title": "t",
        "publication_date": "2020-01-01",
        "is_retracted": retracted,
        "is_paratext": False,
        "referenced_works": [],
    }


class Recorder:
    """Handler that records requests and serves canned list responses."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        qs = parse_qs(urlparse(str(request.url)).query)
        filt = qs.get("filter", [""])[0]
        if filt.startswith("doi:"):
            dois = filt[len("doi:") :].split("|")
            return httpx.Response(
                200, json={"results": [make_work(d) for d in dois], "meta": {}}
            )
        return httpx.Response(200, json={"results": [], "meta": {}})


def client_with(handler, tmp_path: Path, **kw) -> OpenAlexClient:
    return OpenAlexClient(
        api_key="k",
        mailto="m@example.org",
        transport=httpx.MockTransport(handler),
        cache_dir=tmp_path / "cache",
        retry_base_seconds=0.0,
        **kw,
    )


def test_key_and_mailto_attached(tmp_path: Path) -> None:
    rec = Recorder()
    client_with(rec, tmp_path).get_works_by_dois(["10.1/a"])
    qs = parse_qs(urlparse(str(rec.requests[0].url)).query)
    assert qs["api_key"] == ["k"]
    assert qs["mailto"] == ["m@example.org"]


def test_batch_splits_above_50(tmp_path: Path) -> None:
    rec = Recorder()
    dois = [f"10.1/x{i}" for i in range(120)]
    found = client_with(rec, tmp_path).get_works_by_dois(dois)
    assert len(rec.requests) == 3  # 50 + 50 + 20
    assert len(found) == 120


def test_metacharacter_dois_fall_back_to_single_lookup(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/works/"):
            return httpx.Response(200, json=make_work("10.1/a,b"))
        pytest.fail(f"unexpected batch request: {request.url}")

    found = client_with(handler, tmp_path).get_works_by_dois(["10.1/a,b"])
    assert "10.1/a,b" in found


def test_disk_cache_prevents_second_hit(tmp_path: Path) -> None:
    rec = Recorder()
    c = client_with(rec, tmp_path)
    c.get_works_by_dois(["10.1/a"])
    c.get_works_by_dois(["10.1/a"])
    assert len(rec.requests) == 1


def test_429_retries_then_succeeds(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"results": [make_work("10.1/a")], "meta": {}})

    found = client_with(handler, tmp_path).get_works_by_dois(["10.1/a"])
    assert calls["n"] == 2
    assert "10.1/a" in found


def test_get_work_404_returns_none(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    assert client_with(handler, tmp_path).get_work("10.1/missing") is None


def test_institution_pagination_follows_cursor(tmp_path: Path) -> None:
    pages = {
        "*": {"results": [make_work("10.1/p1")], "meta": {"next_cursor": "c2"}},
        "c2": {"results": [make_work("10.1/p2")], "meta": {"next_cursor": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(request.url)).query)
        return httpx.Response(200, json=pages[qs["cursor"][0]])

    works = list(client_with(handler, tmp_path).list_institution_works("https://ror.org/x"))
    assert len(works) == 2


def test_openalex_signal_only_when_retracted() -> None:
    assert openalex_signal(make_work("10.1/a")) is None
    sig = openalex_signal(make_work("10.1/a", retracted=True))
    assert sig is not None
    assert sig.kind is StatusKind.RETRACTED
    assert sig.strength is Strength.WEAK


def test_paratext_note() -> None:
    w = make_work("10.1/a")
    assert paratext_note(w) is None
    w["is_paratext"] = True
    assert paratext_note(w) is not None
