"""Tests for shared-session Gemini notebook conversation discovery."""

from __future__ import annotations

import json
import logging
from unittest.mock import Mock

import pytest

from notebooklm_tools.mcp.tools import gemini_conversations as tool
from notebooklm_tools.services import gemini_conversations as svc
from notebooklm_tools.services.errors import ValidationError

NB = "d35997af-19b3-415a-b215-c59a50f443bb"
OTHER_NB = "b5ff9051-de3b-49b7-9470-98253547850e"
S1 = "11111111-1111-4111-8111-111111111111"
S2 = "22222222-2222-4222-8222-222222222222"
UNKNOWN = "33333333-3333-4333-8333-333333333333"
CID = "c_123456789abcdef001122334455667788"


def _chat_row(nb=NB, cid=CID, title="Gemini notebook discussion"):
    row = [None] * 22
    row[0] = cid
    row[1] = title
    row[7] = "notebooks/" + nb
    return row


def _metadata(nb=NB, ids=(S1, S2)):
    source_rows = []
    for sid in ids:
        row = [None] * 22
        row[2] = "Example title"
        row[5] = f"notebooks/{nb}/sources/{sid}"
        source_rows.append(row)
    fields = [None] * 15
    fields[10] = [source_rows]
    return [["notebooks/" + nb, fields, [], True]]


def _frame(rpc, payload):
    return ")]}'\n" + json.dumps(
        [["wrb.fr", rpc, json.dumps(payload, separators=(",", ":")), None]]
    )


BOOTSTRAP = (
    "<script>window.WIZ_global_data={"
    '"SNlM0e":"private-csrf-token","cfb2h":"boq-gemini-web-uiserver_20261103",'
    '"FdrFJe":"private-session-id"};</script>'
)


class Response:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


class FakeHTTP:
    def __init__(self, metadata=None, rows=None, *, get_status=200, post_status=200):
        self.metadata = metadata if metadata is not None else _metadata()
        self.rows = rows if rows is not None else [_chat_row()]
        self.get_status = get_status
        self.post_status = post_status
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return Response(self.get_status, BOOTSTRAP)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if self.post_status != 200:
            return Response(self.post_status, "sensitive token in error")
        rpc = kwargs["params"]["rpcids"]
        payload = self.metadata if rpc == "HcT8bb" else [None, None, self.rows]
        return Response(200, _frame(rpc, payload))


def _client(monkeypatch, http=None, *, sources=None):
    http = http or FakeHTTP()
    client = Mock()
    client._profile_name = "pte"
    monkeypatch.setenv(svc.ACCOUNT_BINDINGS_ENV, '{"pte":0}')
    client._get_client.return_value = http
    source_list = (
        sources
        if sources is not None
        else [
            {"id": S1, "title": "Alpha"},
            {"id": S2, "title": "Beta"},
        ]
    )
    monkeypatch.setattr(
        svc.notebooks_service,
        "get_notebook",
        lambda selected, notebook: {
            "notebook_id": notebook,
            "title": "Known notebook",
            "sources": source_list,
        },
    )
    return client, http


def test_bootstrap_parsing():
    assert svc._extract_bootstrap(BOOTSTRAP)["FdrFJe"] == "private-session-id"


def test_bootstrap_missing_or_invalid():
    with pytest.raises(svc.GeminiContinuityError, match="schema"):
        svc._extract_bootstrap('<script>"SNlM0e":"token"</script>')
    with pytest.raises(svc.GeminiContinuityError, match="unavailable"):
        svc._extract_bootstrap("")


def test_parse_conversations_notebook_scope():
    payload = [
        None,
        None,
        [
            _chat_row(),
            _chat_row(nb=OTHER_NB, cid="c_other_123456789"),
            _chat_row(cid="c_other_456789012", title="Second"),
            _chat_row(),  # dedupe
            ["unexpected"],
        ],
    ]
    result = svc._parse_conversations(payload, NB, 10)
    assert [x["title"] for x in result["conversations"]] == [
        "Gemini notebook discussion",
        "Second",
    ]
    assert result["skipped_other_notebook_rows"] == 1
    assert result["skipped_malformed_rows"] == 1
    assert result["complete_history"] is False
    assert all(
        x["provenance"] == "gemini_notebook_scoped_conversation" for x in result["conversations"]
    )


def test_title_bounded():
    result = svc._parse_conversations([None, None, [_chat_row(title="a" * 1000)]], NB, 10)
    assert len(result["conversations"][0]["title"]) == svc.MAX_TITLE_CHARS


def test_malformed_conversation_structure():
    with pytest.raises(svc.GeminiContinuityError, match="schema"):
        svc._parse_conversations({"private": "information"}, NB, 10)


def test_native_source_overlap_and_wrong_account():
    assert svc._parse_native_source_overlap(_metadata(), NB, {S1, S2}) == 2
    with pytest.raises(svc.GeminiContinuityError, match="different notebook"):
        svc._parse_native_source_overlap(_metadata(nb=OTHER_NB), NB, {S1})
    with pytest.raises(svc.GeminiContinuityError, match="Could not verify"):
        svc._parse_native_source_overlap(_metadata(ids=(UNKNOWN,)), NB, {S1})


def test_full_readonly_success(monkeypatch):
    client, http = _client(monkeypatch)
    result = svc.list_gemini_notebook_conversations(client, NB, limit=10)
    assert result["returned_count"] == 1
    assert result["verified_native_source_ids"] == 2
    assert result["notebooklm_chat_equivalence"] == "not_established"
    assert len(http.get_calls) == 1
    assert len(http.post_calls) == 2
    assert [call[1]["params"]["rpcids"] for call in http.post_calls] == [
        "HcT8bb",
        "MaZiqc",
    ]
    assert all("private" not in str(result).lower() for _ in [0])
    assert http.post_calls[0][1]["data"]["at"] == "private-csrf-token"


@pytest.mark.parametrize("bad", ["not-uuid", "", None, NB + "suffix"])
def test_reject_invalid_notebook(monkeypatch, bad):
    client, http = _client(monkeypatch)
    with pytest.raises(ValidationError, match="notebook_id"):
        svc.list_gemini_notebook_conversations(client, bad)
    assert http.get_calls == []


@pytest.mark.parametrize("bad", [0, 11, True, "10", -1])
def test_reject_invalid_limits(monkeypatch, bad):
    client, http = _client(monkeypatch)
    with pytest.raises(ValidationError, match="limit"):
        svc.list_gemini_notebook_conversations(client, NB, limit=bad)
    assert http.get_calls == []


@pytest.mark.parametrize("bad", [-1, 10, True, "0"])
def test_reject_invalid_account_index(monkeypatch, bad):
    client, http = _client(monkeypatch)
    with pytest.raises(ValidationError, match="gemini_account_index"):
        svc.list_gemini_notebook_conversations(client, NB, gemini_account_index=bad)
    assert http.get_calls == []


def test_explicit_account_index_no_fallback(monkeypatch):
    client, http = _client(monkeypatch)
    monkeypatch.setenv(svc.ACCOUNT_BINDINGS_ENV, '{"pte":2}')
    svc.list_gemini_notebook_conversations(client, NB, gemini_account_index=2)
    assert all("/u/2/" in url for url, _ in http.post_calls)
    assert len(http.post_calls) == 2


def test_missing_binding_rejected_before_network(monkeypatch):
    client, http = _client(monkeypatch)
    monkeypatch.delenv(svc.ACCOUNT_BINDINGS_ENV)
    with pytest.raises(svc.GeminiContinuityError, match="not configured"):
        svc.list_gemini_notebook_conversations(client, NB)
    assert not http.get_calls and not http.post_calls


def test_cross_account_index_rejected_before_network(monkeypatch):
    client, http = _client(monkeypatch)
    with pytest.raises(svc.GeminiContinuityError, match="does not match"):
        svc.list_gemini_notebook_conversations(client, NB, gemini_account_index=1)
    assert not http.get_calls and not http.post_calls


@pytest.mark.parametrize(
    "binding", ['{"pte":true}', '{"pte":"0"}', '{"other":0}', "{}", "broken-json"]
)
def test_bad_or_unbound_profile_config_rejected(monkeypatch, binding):
    client, http = _client(monkeypatch)
    monkeypatch.setenv(svc.ACCOUNT_BINDINGS_ENV, binding)
    with pytest.raises(svc.GeminiContinuityError):
        svc.list_gemini_notebook_conversations(client, NB)
    assert not http.get_calls and not http.post_calls


def test_env_auth_without_named_profile_rejected(monkeypatch):
    client, http = _client(monkeypatch)
    client._profile_name = None
    with pytest.raises(svc.GeminiContinuityError, match="named"):
        svc.list_gemini_notebook_conversations(client, NB)
    assert not http.get_calls and not http.post_calls


def test_verbose_http_logging_rejected_before_network(monkeypatch, caplog):
    client, http = _client(monkeypatch)
    with (
        caplog.at_level(logging.INFO, logger="httpx"),
        pytest.raises(svc.GeminiContinuityError, match="verbose HTTP"),
    ):
        svc.list_gemini_notebook_conversations(client, NB)
    assert not http.get_calls and not http.post_calls


def test_unavailable_gemini_account_fails_closed(monkeypatch):
    client, http = _client(monkeypatch, FakeHTTP(metadata=_metadata(nb=OTHER_NB)))
    with pytest.raises(svc.GeminiContinuityError, match="different notebook"):
        svc.list_gemini_notebook_conversations(client, NB)
    assert len(http.post_calls) == 1  # never returns conversation metadata


def test_empty_native_inventory_fails_closed(monkeypatch):
    client, http = _client(monkeypatch, sources=[])
    with pytest.raises(svc.GeminiContinuityError, match="without native sources"):
        svc.list_gemini_notebook_conversations(client, NB)
    assert http.get_calls == []


def test_expired_session_no_retry_or_account_switch(monkeypatch):
    client, http = _client(monkeypatch, FakeHTTP(post_status=403))
    with pytest.raises(svc.GeminiContinuityError, match="visible login"):
        svc.list_gemini_notebook_conversations(client, NB)
    assert len(http.get_calls) == 1
    assert len(http.post_calls) == 1


def test_failed_bootstrap_no_rpc(monkeypatch):
    client, http = _client(monkeypatch, FakeHTTP(get_status=302))
    with pytest.raises(svc.GeminiContinuityError, match="visible login"):
        svc.list_gemini_notebook_conversations(client, NB)
    assert http.post_calls == []


def test_mcp_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS", raising=False)
    res = tool.gemini_notebook_conversation_list(NB)
    assert res["status"] == "error"
    assert "disabled" in res["error"]


def test_mcp_enabled(monkeypatch):
    client, _ = _client(monkeypatch)
    monkeypatch.setenv("NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS", "1")
    monkeypatch.setattr(tool, "get_client", lambda: client)
    res = tool.gemini_notebook_conversation_list(NB)
    assert res["status"] == "success"
    assert res["conversation_namespace"] == "gemini"


def test_mcp_does_not_disclose_transport_errors(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS", "1")

    def broken():
        raise RuntimeError("private-cookie-token")

    monkeypatch.setattr(tool, "get_client", broken)
    res = tool.gemini_notebook_conversation_list(NB)
    assert res["status"] == "error"
    assert "private-cookie-token" not in json.dumps(res)


def test_httpx_logging_redacts_url(caplog):
    logger = logging.getLogger("httpx._client")
    with caplog.at_level(logging.INFO, logger="httpx._client"), svc._guard_http_logs():
        logger.info("HTTP Request: POST https://gemini.google.com/u/0/?f.sid=SECRET")
        logger.info("Ordinary unrelated HTTP request")
    assert "SECRET" not in caplog.text
    assert "Ordinary unrelated HTTP request" in caplog.text


@pytest.mark.asyncio
async def test_mcp_registered_in_chat_group():
    from notebooklm_tools.mcp import server, tool_groups

    mcp_entry = await server.mcp.get_tool("gemini_notebook_conversation_list")
    assert mcp_entry is not None
    assert "gemini_notebook_conversation_list" in tool_groups.TOOL_GROUPS["chat"]
