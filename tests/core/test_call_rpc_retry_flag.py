"""_call_rpc must be able to skip 5xx replays for non-idempotent kickoffs."""

from unittest.mock import MagicMock

import httpx
import pytest

from notebooklm_tools.core.base import BaseClient


def _client_returning(status_code: int) -> BaseClient:
    client = BaseClient(cookies={"SID": "x"}, csrf_token="t")
    request = httpx.Request("POST", "https://notebook.google.com/x")
    response = httpx.Response(status_code, request=request, text="err")
    http = MagicMock()
    http.post.return_value = response
    client._get_client = MagicMock(return_value=http)
    client._cdp_rpc_transport_enabled = MagicMock(return_value=False)
    return client


def test_server_error_is_not_replayed_when_disabled(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = _client_returning(502)
    with pytest.raises(httpx.HTTPStatusError):
        client._call_rpc("Rytqqe", [], "/notebook/nb", retry_server_errors=False)
    assert client._get_client.return_value.post.call_count == 1


def test_server_error_is_replayed_by_default(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = _client_returning(502)
    with pytest.raises(httpx.HTTPStatusError):
        client._call_rpc("wXbhsf", [], "/")
    assert client._get_client.return_value.post.call_count > 1


@pytest.mark.parametrize(
    "rpc_id",
    ["CCqFvf", "WWINqb", "agX4Bc", "le8sX", "GyzE7e", "Rytqqe", "future-unknown-rpc", "cFji9"],
)
@pytest.mark.parametrize("status", [429, 502])
def test_mutation_or_unknown_rpc_is_not_replayed_by_default(monkeypatch, rpc_id, status):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = _client_returning(status)
    with pytest.raises(httpx.HTTPStatusError):
        client._call_rpc(rpc_id, [], "/")
    assert client._get_client.return_value.post.call_count == 1


@pytest.mark.parametrize("status", [429, 502])
@pytest.mark.parametrize("rpc_id", ["wXbhsf", "rG2vCb", "EylDcb"])
def test_read_only_rpc_retains_server_retry(monkeypatch, status, rpc_id):
    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = _client_returning(status)
    with pytest.raises(httpx.HTTPStatusError):
        client._call_rpc(rpc_id, [], "/")
    assert client._get_client.return_value.post.call_count > 1


@pytest.mark.parametrize("rpc_id, expected_calls", [("CCqFvf", 1), ("wXbhsf", 4)])
def test_cdp_rpc_rate_limit_only_replays_read_only_operations(monkeypatch, rpc_id, expected_calls):
    from notebooklm_tools.core.errors import ResourceExhaustedError

    monkeypatch.setattr("time.sleep", lambda *_: None)
    client = BaseClient(cookies={"SID": "x"}, csrf_token="t")
    client._cdp_rpc_transport_enabled = MagicMock(return_value=True)
    client._prepare_cdp_transport = MagicMock()
    client._build_request_body = MagicMock(return_value="f.req=...")
    client._build_url = MagicMock(return_value="https://notebook.google.com/")
    client._post_form_via_cdp = MagicMock(return_value="response")
    client._parse_response = MagicMock(return_value=[])
    client._extract_rpc_result = MagicMock(side_effect=ResourceExhaustedError("rate limited"))

    with pytest.raises(ResourceExhaustedError):
        client._call_rpc(rpc_id, [], "/")
    assert client._post_form_via_cdp.call_count == expected_calls
