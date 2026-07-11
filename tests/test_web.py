"""Web checker tests: form GET, DOI check, .bib upload, JSON mode (no network)."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

import citeguard.web as web
from citeguard.resources import Resources
from citeguard.retractionwatch import RWIndex
from tests.conftest import FakeOpenAlexHandler, make_cr_client, make_oa_client, openalex_work

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(rw_index: RWIndex, tmp_path: Path, monkeypatch) -> TestClient:
    oa = make_oa_client(
        FakeOpenAlexHandler([openalex_work("10.9999/paper.1", retracted=True)])
    )
    resources = Resources(
        rw_index=rw_index,
        oa_client=oa,
        cr_client=make_cr_client({}),
        hijacked=None,
        data_dir=tmp_path,
    )
    monkeypatch.setattr("citeguard.resources._resources", resources)
    return TestClient(web.app)


def test_index_renders_form(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Check references" in resp.text
    assert "<textarea" in resp.text


def test_check_dois_html(client: TestClient) -> None:
    resp = client.post("/check", data={"dois": "10.9999/paper.1\n10.9999/clean.1"})
    assert resp.status_code == 200
    assert "Retracted" in resp.text
    assert "Clean" in resp.text
    assert "2 reference(s) checked · 1 flagged" in resp.text


def test_check_dois_json(client: TestClient) -> None:
    resp = client.post(
        "/check", data={"dois": "10.9999/paper.1"}, headers={"accept": "application/json"}
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["references"][0]["kind"] == "retracted"
    assert payload["references"][0]["ref"] == "10.9999/paper.1"


def test_bib_upload(client: TestClient) -> None:
    bib = (FIXTURES / "refs_mini.bib").read_bytes()
    resp = client.post("/check", files={"bibfile": ("refs.bib", bib, "text/plain")})
    assert resp.status_code == 200
    assert "Retracted" in resp.text  # has_doi_field -> 10.9999/paper.1
    assert "has_doi_field" in resp.text  # bib key shown as the reference label


def test_empty_submit_is_harmless(client: TestClient) -> None:
    resp = client.post("/check", data={"dois": ""})
    assert resp.status_code == 200
    assert "reference(s) checked" not in resp.text


def test_html_is_escaped(client: TestClient) -> None:
    resp = client.post("/check", data={"dois": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text
