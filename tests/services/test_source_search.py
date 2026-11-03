"""Tests for native read-only ASU5Oe source search, limits, and MCP integration."""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock

import pytest

from notebooklm_tools.mcp.tools import native_source_search as mcp_tool
from notebooklm_tools.services import source_search as service

NB = "d35997af-19b3-415a-b215-c59a50f443bb"
S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"


def response(texts: list[str], source_id: str = S1):
    chunks = [
        [[[[text]]], index, [[None, index * 3, index * 3 + len(text)]]]
        for index, text in enumerate(texts)
    ]
    return [[[source_id, chunks]]]


def native_client(monkeypatch, result=None):
    def get_notebook(_client, nb):
        assert nb == NB
        return {
            "notebook_id": NB,
            "sources": [
                {"id": S1, "title": "Alpha"},
                {"id": S2, "title": "Beta"},
            ],
        }

    monkeypatch.setattr(service.notebooks_service, "get_notebook", get_notebook)
    client = Mock()
    client._call_rpc.return_value = result if result is not None else response(["secret passage"])
    return client


def test_source_search_uses_existing_notebooklm_transport(monkeypatch):
    client = native_client(monkeypatch)
    result = service.search_native_sources(client, NB, "agent orchestration")
    client._call_rpc.assert_called_once_with(
        "ASU5Oe",
        [NB, "agent orchestration", None, [1]],
        path=f"/notebook/{NB}",
        timeout=30,
        retry_server_errors=False,
    )
    assert result["returned_passages"] == 1
    assert result["results"][0]["excerpt"] == "secret passage"
    assert result["results"][0]["source_title"] == "Alpha"
    assert result["query"] == "[omitted]"
    assert result["ranking_score_available"] is False


def test_source_filter_uses_verified_wire_shape(monkeypatch):
    client = native_client(monkeypatch)
    service.search_native_sources(client, NB, "context", source_ids=[S1, S2])
    call = client._call_rpc.call_args
    assert call.args[1] == [NB, "context", None, [1], [[[S1, S2]]]]


def test_unknown_source_fails_before_network(monkeypatch):
    client = native_client(monkeypatch)
    with pytest.raises(service.SourceSearchError, match="absent"):
        service.search_native_sources(client, NB, "context", source_ids=[OTHER])
    client._call_rpc.assert_not_called()


@pytest.mark.parametrize("invalid", ["", "foo", NB + "garbage", 12, None])
def test_invalid_notebook_id(invalid):
    with pytest.raises(service.SourceSearchError, match="notebook_id"):
        service.validate_search(invalid, "valid", None, 8, 900)


@pytest.mark.parametrize("invalid", ["", "   ", "x" * 1001, None, 17])
def test_invalid_queries(invalid):
    with pytest.raises(service.SourceSearchError, match="query"):
        service.validate_search(NB, invalid, None, 8, 900)


@pytest.mark.parametrize("invalid", [0, 21, -1, True, "8"])
def test_invalid_result_limits(invalid):
    with pytest.raises(service.SourceSearchError, match="max_results"):
        service.validate_search(NB, "q", None, invalid, 900)


@pytest.mark.parametrize("invalid", [0, 1801, -10, False, "900"])
def test_invalid_snippet_limits(invalid):
    with pytest.raises(service.SourceSearchError, match="snippet_chars"):
        service.validate_search(NB, "q", None, 8, invalid)


@pytest.mark.parametrize("invalid", [[], [NB] * 11, [S1, S1], [OTHER, "bad"]])
def test_invalid_source_filters(invalid):
    with pytest.raises(service.SourceSearchError):
        service.validate_search(NB, "q", invalid, 8, 900)


def test_allow_uppercase_uuid_and_normalize():
    nb, query, sources = service.validate_search(NB.upper(), "  query  ", [S1.upper()], 8, 900)
    assert (nb, query, sources) == (NB, "query", [S1])


def test_snippet_limit_and_total_budget():
    items = response(["a" * 2000] * 20)[0][0][1]
    output = service.extract_passages(
        [[[S1, items]]],
        native_sources={S1: "Alpha"},
        source_filter=None,
        max_results=20,
        snippet_chars=1800,
    )
    assert sum(len(x["excerpt"]) for x in output["results"]) <= service.MAX_TOTAL_CHARS
    assert output["truncated"] is True
    assert all(len(x["excerpt"]) <= 1800 for x in output["results"])


def test_diversifies_across_source_groups():
    result = service.extract_passages(
        [
            [
                [S1, response(["A1", "A2"])[0][0][1]],
                [S2, response(["B1", "B2"])[0][0][1]],
            ]
        ],
        native_sources={S1: "Alpha", S2: "Beta"},
        source_filter=None,
        max_results=3,
        snippet_chars=900,
    )
    assert [hit["source_id"] for hit in result["results"]] == [S1, S2, S1]
    assert [hit["excerpt"] for hit in result["results"]] == ["A1", "B1", "A2"]
    assert result["selection_policy"] == "round_robin_by_source"
    assert result["truncated"] is True


def test_result_count_cap():
    result = service.extract_passages(
        response(["a"] * 50),
        native_sources={S1: "Alpha"},
        source_filter=None,
        max_results=3,
        snippet_chars=900,
    )
    assert result["returned_passages"] == 3
    assert result["available_passages"] == 50
    assert result["truncated"] is True


def test_unknown_source_excluded():
    result = service.extract_passages(
        response(["private"], source_id=OTHER),
        native_sources={S1: "Alpha"},
        source_filter=None,
        max_results=8,
        snippet_chars=900,
    )
    assert result["returned_passages"] == 0
    assert result["excluded_unknown_or_unrequested_sources"] == 1


def test_source_filter_applied_against_response():
    result = service.extract_passages(
        response(["private"], source_id=S2),
        native_sources={S1: "Alpha", S2: "Beta"},
        source_filter={S1},
        max_results=8,
        snippet_chars=900,
    )
    assert result["results"] == []
    assert result["excluded_unknown_or_unrequested_sources"] == 1


def test_malformed_response_fails_safely():
    with pytest.raises(service.SourceSearchError, match="unrecognized"):
        service.extract_passages(
            {"secret": "sensitive"},
            native_sources={},
            source_filter=None,
            max_results=8,
            snippet_chars=900,
        )


def test_malformed_chunk_not_used():
    result = service.extract_passages(
        [[[S1, [[["unexpected"]], [None, 42]]]]],
        native_sources={S1: "Alpha"},
        source_filter=None,
        max_results=8,
        snippet_chars=900,
    )
    assert result["returned_passages"] == 0


def test_mcp_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH", raising=False)
    result = mcp_tool.source_search(NB, "q")
    assert result["status"] == "error"
    assert "disabled" in result["error"]


def test_mcp_enabled_with_native_client(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH", "1")
    client = native_client(monkeypatch)
    monkeypatch.setattr(mcp_tool, "get_client", lambda: client)
    result = mcp_tool.source_search(NB, "q")
    assert result["status"] == "success"
    assert result["returned_passages"] == 1


def test_mcp_never_discloses_transport_errors(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH", "1")

    def raising(*_args, **_kwargs):
        raise RuntimeError("sensitive-token-should-not-be-logged")

    monkeypatch.setattr(mcp_tool, "get_client", raising)
    result = mcp_tool.source_search(NB, "q")
    assert result["status"] == "error"
    assert "sensitive-token" not in json.dumps(result)


def test_native_rpc_suppresses_debug_payload_logging(caplog):
    from notebooklm_tools.core.base import BaseClient

    fake = type("MinimalClient", (), {})()
    response_obj = Mock(status_code=200, text="PRIVATE_PASSAGE_DATA")
    transport = Mock()
    transport.post.return_value = response_obj
    fake.RPC_SEARCH_RELEVANT_CHUNKS = "ASU5Oe"
    fake._cdp_rpc_transport_enabled = lambda: False
    fake._get_client = lambda: transport
    fake._build_request_body = lambda *_args: "PRIVATE_QUERY_DATA"
    fake._build_url = lambda *_args: "https://notebooklm.google.com/test"
    fake._parse_response = lambda *_args: []
    fake._extract_rpc_result = lambda *_args: [["PRIVATE_PASSAGE_DATA"]]

    with caplog.at_level(logging.DEBUG, logger="notebooklm_tools.core.base"):
        BaseClient._call_rpc(fake, "ASU5Oe", ["PRIVATE_QUERY_DATA"])
    assert "PRIVATE_QUERY_DATA" not in caplog.text
    assert "PRIVATE_PASSAGE_DATA" not in caplog.text


@pytest.mark.asyncio
async def test_mcp_registers_without_logged_tool_wrapper():
    from notebooklm_tools.mcp import server

    tool = await server.mcp.get_tool("source_search")
    assert tool is not None
    assert tool.name == "source_search"
