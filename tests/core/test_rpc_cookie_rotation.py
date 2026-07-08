"""Tests for automatic cookie rotation in BaseClient._call_rpc."""

from unittest.mock import patch

import httpx

from notebooklm_tools.core.base import BaseClient
from notebooklm_tools.core.cookie_rotation import CookieRotationResult


def _client(cookies=None):
    if cookies is None:
        cookies = {"SID": "old"}
    with patch.object(BaseClient, "_refresh_auth_tokens"):
        return BaseClient(cookies=cookies, csrf_token="t")


def _fake_resp():
    return type("R", (), {"text": "", "status_code": 200, "raise_for_status": lambda self: None})()


OK_CHUNK = [[["wrb.fr", "EXPECTED", "[1]", None, None, None, "generic"]]]


def test_call_rpc_rotates_cookies_before_first_attempt():
    client = _client()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_maybe_rotate_cookies") as mock_rotate,
        patch.object(client, "_parse_response", return_value=OK_CHUNK),
    ):
        mock_get_client.return_value.post.return_value = _fake_resp()
        client._call_rpc("EXPECTED", [])

    mock_rotate.assert_called_once_with(mock_get_client.return_value)


def test_call_rpc_does_not_rotate_on_auth_retry():
    client = _client()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_maybe_rotate_cookies") as mock_rotate,
        patch.object(client, "_parse_response", return_value=OK_CHUNK),
    ):
        mock_get_client.return_value.post.return_value = _fake_resp()
        client._call_rpc("EXPECTED", [], _retry=True)

    mock_rotate.assert_not_called()


def test_call_rpc_rotates_once_across_connect_timeout_retries():
    client = _client()

    with (
        patch.object(client, "_get_client") as mock_get_client,
        patch.object(client, "_maybe_rotate_cookies") as mock_rotate,
        patch.object(client, "_parse_response", return_value=OK_CHUNK),
        patch("time.sleep"),
    ):
        mock_get_client.return_value.post.side_effect = [
            httpx.ConnectTimeout("connect timed out"),
            _fake_resp(),
        ]
        client._call_rpc("EXPECTED", [])

    mock_rotate.assert_called_once()


def test_maybe_rotate_cookies_success_updates_cookies_and_cache():
    client = _client(cookies={"SID": "old"})
    http_client = httpx.Client()
    http_client.cookies.set("SID", "fresh", domain=".google.com")

    cached = type("T", (), {"cookies": {"SID": "old"}})()

    with (
        patch(
            "notebooklm_tools.core.cookie_rotation.rotate_google_cookies",
            return_value=CookieRotationResult(attempted=True, success=True, status_code=200),
        ),
        patch("notebooklm_tools.core.auth.load_cached_tokens", return_value=cached),
        patch("notebooklm_tools.core.auth.save_tokens_to_cache") as mock_save,
    ):
        client._maybe_rotate_cookies(http_client)

    assert client.cookies["SID"] == "fresh"
    assert cached.cookies == client.cookies
    mock_save.assert_called_once_with(cached, silent=True)


def test_maybe_rotate_cookies_failure_leaves_state_untouched():
    client = _client(cookies={"SID": "old"})

    with (
        patch(
            "notebooklm_tools.core.cookie_rotation.rotate_google_cookies",
            return_value=CookieRotationResult(
                attempted=False, success=False, skipped_reason="recent_process_attempt"
            ),
        ),
        patch("notebooklm_tools.core.auth.save_tokens_to_cache") as mock_save,
    ):
        client._maybe_rotate_cookies(httpx.Client())

    assert client.cookies == {"SID": "old"}
    mock_save.assert_not_called()


def test_maybe_rotate_cookies_skips_when_no_cookies():
    client = _client(cookies={})

    with patch("notebooklm_tools.core.cookie_rotation.rotate_google_cookies") as mock_rotate:
        client._maybe_rotate_cookies(httpx.Client())

    mock_rotate.assert_not_called()
