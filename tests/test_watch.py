"""Watch tests: ID-map building (checkpointed) and the local-join digest."""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from citeguard.retractionwatch import RWIndex
from citeguard.status import StatusKind
from citeguard.watch import build_rw_id_map, watch_institution
from tests.conftest import FakeOpenAlexHandler, make_oa_client, openalex_work


def test_build_rw_id_map_checkpoints_and_resumes(rw_index: RWIndex, tmp_path: Path) -> None:
    known = [openalex_work(doi) for doi in sorted(rw_index)[:3]]
    handler = FakeOpenAlexHandler(known)
    path = tmp_path / "map.json"

    # simulate an interrupted first run: zero requests allowed -> no progress
    build_rw_id_map(rw_index, make_oa_client(handler), path, max_requests=0)
    assert not path.exists()

    mapping = build_rw_id_map(rw_index, make_oa_client(handler), path)
    assert path.exists()
    assert len(mapping) == len(rw_index)
    assert sum(1 for i in mapping.values() if i) == 3  # only works OpenAlex "knows"

    # resume: nothing left to do -> no new requests
    before = len(handler.requests)
    build_rw_id_map(rw_index, make_oa_client(handler), path)
    assert len(handler.requests) == before


def institution_router(
    institution_works: list[dict], corpus: list[dict]
) -> "httpx.MockTransport":
    """Routes ROR list queries to `institution_works`; everything else to corpus."""
    inner = FakeOpenAlexHandler(corpus)

    def call(request: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(request.url)).query)
        if qs.get("filter", [""])[0].startswith("authorships.institutions.ror:"):
            return httpx.Response(
                200, json={"results": institution_works, "meta": {"next_cursor": None}}
            )
        return inner(request)

    return httpx.MockTransport(call)


def make_routed_client(transport: httpx.MockTransport):
    from citeguard.openalex import OpenAlexClient

    return OpenAlexClient(
        api_key="test-key",
        mailto="test@example.org",
        transport=transport,
        cache_dir=None,
        retry_base_seconds=0.0,
    )


def test_watch_flags_direct_and_citing(rw_index: RWIndex, tmp_path: Path) -> None:
    flagged = openalex_work("10.9999/paper.1", retracted=True)  # retracted in rw_mini
    citer = openalex_work("10.9999/inst.paper", referenced_works=[flagged["id"]])
    own_flagged = openalex_work("10.9999/paper.3")  # EoC in rw_mini

    oa = make_routed_client(
        institution_router([citer, own_flagged], [flagged, citer, own_flagged])
    )
    id_map = tmp_path / "map.json"
    id_map.write_text(json.dumps({"10.9999/paper.1": flagged["id"]}))

    digest = watch_institution(
        "https://ror.org/test",
        None,
        rw_index=rw_index,
        oa_client=oa,
        id_map_path=id_map,
        state_dir=tmp_path / "watch",
    )
    assert digest.works_scanned == 2
    assert [s.kind for s in digest.flagged_works] == [StatusKind.EXPRESSION_OF_CONCERN]
    assert len(digest.works_citing_flagged) == 1
    hit = digest.works_citing_flagged[0]
    assert hit.flagged_reference.kind is StatusKind.RETRACTED
    assert hit.citing_work_id == citer["id"]
    assert len(digest.new_flag_keys) == 2

    # second run: same flags -> nothing new
    digest2 = watch_institution(
        "https://ror.org/test",
        None,
        rw_index=rw_index,
        oa_client=oa,
        id_map_path=id_map,
        state_dir=tmp_path / "watch",
    )
    assert digest2.new_flag_keys == []


def test_watch_without_id_map_degrades_gracefully(rw_index: RWIndex, tmp_path: Path) -> None:
    oa = make_routed_client(institution_router([], []))
    digest = watch_institution(
        "https://ror.org/test",
        "2024-01-01",
        rw_index=rw_index,
        oa_client=oa,
        id_map_path=tmp_path / "missing.json",
        state_dir=tmp_path / "watch",
    )
    assert digest.works_citing_flagged == []
    assert any("ID map" in n for n in digest.notes)
