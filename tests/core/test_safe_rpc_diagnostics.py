"""Debug diagnostics retain operational metadata without exposing payloads."""

import logging
from unittest.mock import MagicMock

import httpx

from notebooklm_tools.core.base import BaseClient


def test_debug_rpc_logging_does_not_leak_request_or_response(caplog):
    client = BaseClient(cookies={"SID": "private-session"}, csrf_token="token")
    client._cdp_rpc_transport_enabled = MagicMock(return_value=False)
    client._build_url = MagicMock(return_value="https://notebook.google.com/?f.sid=secret-session")
    client._build_request_body = MagicMock(return_value="secret-request-payload")
    request = httpx.Request("POST", "https://notebook.google.com/")
    response = httpx.Response(200, request=request, text="secret-response-body")
    transport = MagicMock()
    transport.post.return_value = response
    client._get_client = MagicMock(return_value=transport)
    client._parse_response = MagicMock(return_value=[])
    client._extract_rpc_result = MagicMock(return_value={"answer": "secret-result-answer"})

    with caplog.at_level(logging.DEBUG, logger="notebooklm_mcp.api"):
        result = client._call_rpc("wXbhsf", [], "/")

    assert result == {"answer": "secret-result-answer"}
    assert "RPC Call: wXbhsf" in caplog.text
    assert "status=200" in caplog.text
    for secret in (
        "private-session",
        "secret-session",
        "secret-request-payload",
        "secret-response-body",
        "secret-result-answer",
    ):
        assert secret not in caplog.text
