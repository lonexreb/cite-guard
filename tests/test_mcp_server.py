"""MCP server tests: tool registration + one in-memory round trip.

Tool bodies are thin wrappers over checker/watch (tested elsewhere); here we
verify registration, schemas, and JSON serialization end to end.
"""

import json
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import citeguard.mcp_server as srv
from citeguard.retractionwatch import RWIndex
from tests.conftest import FakeOpenAlexHandler, make_cr_client, make_oa_client, openalex_work


@pytest.fixture
def wired_resources(rw_index: RWIndex, tmp_path: Path, monkeypatch) -> None:
    oa = make_oa_client(
        FakeOpenAlexHandler([openalex_work("10.9999/paper.1", retracted=True)])
    )
    cr = make_cr_client({})
    resources = srv.Resources(
        rw_index=rw_index, oa_client=oa, cr_client=cr, hijacked=None, data_dir=tmp_path
    )
    monkeypatch.setattr(srv, "_resources", resources)


async def test_tools_registered_and_status_round_trips(wired_resources) -> None:
    async with create_connected_server_and_client_session(
        srv.app._mcp_server
    ) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools == {"get_editorial_status", "check_references", "watch_institution"}

        result = await client.call_tool(
            "get_editorial_status", {"doi": "10.9999/paper.1"}
        )
        assert not result.isError
        payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert payload["kind"] == "retracted"
        assert payload["evidence_url"] == "https://doi.org/10.9999/notice.1"
        assert payload["confidence"] == "high"


async def test_check_references_requires_exactly_one_input(wired_resources) -> None:
    async with create_connected_server_and_client_session(
        srv.app._mcp_server
    ) as client:
        result = await client.call_tool("check_references", {})
        payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
        assert "error" in payload

        result = await client.call_tool(
            "check_references", {"dois": ["10.9999/paper.1", "10.9999/clean.1"]}
        )
        payload = json.loads(result.content[0].text)  # type: ignore[union-attr]
        kinds = [r["kind"] for r in payload["references"]]
        assert kinds == ["retracted", "none"]
