"""Tests for RPC drift detection and RPC-level retry in BaseClient."""

from unittest.mock import Mock, patch

import httpx
import pytest

from notebooklm_tools.core.base import BaseClient, _rate_limit_max_retries
from notebooklm_tools.core.errors import ResourceExhaustedError, RPCDriftError
from notebooklm_tools.core.retry import DEFAULT_MAX_RETRIES


def _client():
    with patch.object(BaseClient, "_refresh_auth_tokens"):
        return BaseClient(cookies={}, csrf_token="t")


def test_drift_when_other_ids_present_but_not_ours():
    client = _client()
    parsed = [[["wrb.fr", "ROTATED", "[1]", None, None, None, "generic"]]]
    with pytest.raises(RPCDriftError) as exc:
        client._extract_rpc_result(parsed, "EXPECTED")
    msg = str(exc.value)
    assert "EXPECTED" in msg
    assert "ROTATED" in msg
    assert "NOTEBOOKLM_RPC_OVERRIDES" in msg


def test_empty_response_returns_none_not_drift():
    client = _client()
    assert client._extract_rpc_result([], "EXPECTED") is None


def test_matched_chunk_with_null_result_returns_none():
    client = _client()
    parsed = [[["wrb.fr", "EXPECTED", None, None, None, None, "generic"]]]
    assert client._extract_rpc_result(parsed, "EXPECTED") is None


def test_matched_chunk_returns_parsed_json():
    client = _client()
    parsed = [[["wrb.fr", "EXPECTED", "[1,2,3]", None, None, None, "generic"]]]
    assert client._extract_rpc_result(parsed, "EXPECTED") == [1, 2, 3]


def test_call_rpc_retries_on_resource_exhausted(monkeypatch):
    """A read-only RPC retries code-8 RESOURCE_EXHAUSTED, then succeeds."""
    client = _client()

    exhausted = [[["wrb.fr", "wXbhsf", None, None, None, [8], "generic"]]]
    ok = [[["wrb.fr", "wXbhsf", "[1]", None, None, None, "generic"]]]

    fake_resp = type(
        "R", (), {"text": "", "status_code": 200, "raise_for_status": lambda self: None}
    )()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", side_effect=[exhausted, ok]),
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.return_value = fake_resp
        result = client._call_rpc("wXbhsf", [])

    assert result == [1]


def test_call_rpc_resource_exhausted_exhausts_retries(monkeypatch):
    """After max retries, ResourceExhaustedError propagates."""
    client = _client()
    exhausted = [[["wrb.fr", "EXPECTED", None, None, None, [8], "generic"]]]
    fake_resp = type(
        "R", (), {"text": "", "status_code": 200, "raise_for_status": lambda self: None}
    )()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", return_value=exhausted),
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.return_value = fake_resp
        with pytest.raises(ResourceExhaustedError):
            client._call_rpc("EXPECTED", [])


def test_call_rpc_retries_on_connect_timeout():
    """A connect timeout (connection never established) is retried, then succeeds."""
    import httpx

    client = _client()
    ok = [[["wrb.fr", "EXPECTED", "[1]", None, None, None, "generic"]]]
    fake_resp = type(
        "R", (), {"text": "", "status_code": 200, "raise_for_status": lambda self: None}
    )()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", return_value=ok),
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.side_effect = [
            httpx.ConnectTimeout("connect timed out"),
            fake_resp,
        ]
        result = client._call_rpc("EXPECTED", [])

    assert result == [1]
    assert mock_get_client.return_value.post.call_count == 2


def test_call_rpc_connect_timeout_exhausts_retries():
    """After max retries the connect timeout propagates."""
    import httpx

    from notebooklm_tools.core.retry import DEFAULT_MAX_RETRIES

    client = _client()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.side_effect = httpx.ConnectTimeout("connect timed out")
        with pytest.raises(httpx.ConnectTimeout):
            client._call_rpc("EXPECTED", [])

    # initial attempt + DEFAULT_MAX_RETRIES retries
    assert mock_get_client.return_value.post.call_count == DEFAULT_MAX_RETRIES + 1


def test_call_rpc_does_not_retry_read_timeout():
    """A read timeout may already have been processed server-side, so it is NOT
    auto-retried — it propagates after a single attempt."""
    import httpx

    client = _client()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.side_effect = httpx.ReadTimeout("read timed out")
        with pytest.raises(httpx.ReadTimeout):
            client._call_rpc("EXPECTED", [])

    assert mock_get_client.return_value.post.call_count == 1


def _response_with_status(status: int) -> Mock:
    request = httpx.Request(
        "POST",
        "https://notebooklm.google.com/_/LabsTailwindUi/data/batchexecute",
    )
    response = httpx.Response(status, request=request)
    mocked = Mock()
    mocked.status_code = status
    mocked.text = ""
    if status >= 400:
        mocked.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status}",
            request=request,
            response=response,
        )
    else:
        mocked.raise_for_status.return_value = None
    return mocked


def test_rate_limit_retry_limit_defaults_and_validation(monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", raising=False)
    assert _rate_limit_max_retries() == DEFAULT_MAX_RETRIES

    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "invalid")
    assert _rate_limit_max_retries() == DEFAULT_MAX_RETRIES

    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "-2")
    assert _rate_limit_max_retries() == 0


def test_resource_exhausted_has_configurable_retry_ceiling(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "1")
    client = _client()
    exhausted = [[["wrb.fr", "wXbhsf", None, None, None, [8], "generic"]]]
    ok = [[["wrb.fr", "wXbhsf", "[1]", None, None, None, "generic"]]]
    response = _response_with_status(200)

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", side_effect=[exhausted, ok]),
        patch("time.sleep") as sleep,
    ):
        mock_get_client.return_value.post.return_value = response
        result = client._call_rpc("wXbhsf", [])

    assert result == [1]
    assert mock_get_client.return_value.post.call_count == 2
    sleep.assert_called_once()


def test_resource_exhausted_surfaces_immediately_when_limit_is_zero(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "0")
    client = _client()
    exhausted = [[["wrb.fr", "EXPECTED", None, None, None, [8], "generic"]]]
    response = _response_with_status(200)

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", return_value=exhausted),
        patch("time.sleep") as sleep,
    ):
        mock_get_client.return_value.post.return_value = response
        with pytest.raises(ResourceExhaustedError):
            client._call_rpc("EXPECTED", [])

    assert mock_get_client.return_value.post.call_count == 1
    sleep.assert_not_called()


def test_http_429_surfaces_immediately_when_limit_is_zero(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "0")
    client = _client()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch("time.sleep") as sleep,
    ):
        mock_get_client.return_value.post.return_value = _response_with_status(429)
        with pytest.raises(httpx.HTTPStatusError):
            client._call_rpc("EXPECTED", [])

    assert mock_get_client.return_value.post.call_count == 1
    sleep.assert_not_called()


def test_http_5xx_retries_are_not_disabled_by_rate_limit_policy(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "0")
    client = _client()
    ok = [[["wrb.fr", "wXbhsf", "[1]", None, None, None, "generic"]]]

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", return_value=ok),
        patch("time.sleep") as sleep,
    ):
        mock_get_client.return_value.post.side_effect = [
            _response_with_status(503),
            _response_with_status(200),
        ]
        result = client._call_rpc("wXbhsf", [])

    assert result == [1]
    assert mock_get_client.return_value.post.call_count == 2
    sleep.assert_called_once()


def test_connect_retry_is_not_disabled_by_rate_limit_policy(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "0")
    client = _client()
    ok = [[["wrb.fr", "EXPECTED", "[1]", None, None, None, "generic"]]]

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_parse_response", return_value=ok),
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.side_effect = [
            httpx.ConnectTimeout("connect timed out"),
            _response_with_status(200),
        ]
        result = client._call_rpc("EXPECTED", [])

    assert result == [1]
    assert mock_get_client.return_value.post.call_count == 2


def test_cdp_resource_exhausted_surfaces_immediately_when_limit_is_zero(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES", "0")
    client = _client()
    exhausted = [[["wrb.fr", "EXPECTED", None, None, None, [8], "generic"]]]

    with (
        patch.object(client, "_prepare_cdp_transport"),
        patch.object(client, "_build_request_body", return_value="body"),
        patch.object(client, "_build_url", return_value="https://example.test/rpc"),
        patch.object(client, "_post_form_via_cdp", return_value="raw") as post,
        patch.object(client, "_parse_response", return_value=exhausted),
        patch("time.sleep") as sleep,
        pytest.raises(ResourceExhaustedError),
    ):
        client._call_rpc_via_cdp("EXPECTED", [])

    assert post.call_count == 1
    sleep.assert_not_called()
