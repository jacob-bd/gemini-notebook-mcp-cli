# tests/core/test_base.py
"""Tests for BaseClient infrastructure class."""

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest


def test_base_client_import():
    """Test that BaseClient can be imported."""
    from notebooklm_tools.core.base import BaseClient

    assert BaseClient is not None


def test_base_client_init():
    """Test BaseClient initialization with minimal args."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={"test": "cookie"})
        assert client.cookies == {"test": "cookie"}
        assert client._client is None


def test_base_client_init_with_csrf():
    """Test BaseClient initialization with CSRF token (skips refresh)."""
    from notebooklm_tools.core.base import BaseClient

    # When csrf_token is provided, _refresh_auth_tokens should NOT be called
    with patch.object(BaseClient, "_refresh_auth_tokens") as mock_refresh:
        client = BaseClient(cookies={"test": "cookie"}, csrf_token="test_token")
        mock_refresh.assert_not_called()
        assert client.csrf_token == "test_token"


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("Failed to fetch NotebookLM page: HTTP 503"),
        httpx.ReadTimeout("The read operation timed out"),
        OSError("dns lookup failed"),
    ],
)
def test_unreachable_failure_classifies_transport_and_server_errors(failure):
    """Backend transport and 5xx failures must not be treated as auth expiry."""
    from notebooklm_tools.core.base import _is_unreachable_failure

    assert _is_unreachable_failure(failure) is True


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("Authentication expired. accounts.google.com login redirect"),
        ValueError("Authentication expired"),
    ],
)
def test_unreachable_failure_rejects_explicit_auth_expiry(failure):
    """Explicit rejection evidence must continue through auth recovery."""
    from notebooklm_tools.core.base import _is_unreachable_failure

    assert _is_unreachable_failure(failure) is False


def test_build_request_body():
    """Test building RPC request body."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="test_token")
        body = client._build_request_body("testRpc", ["param1"])
        assert "f.req=" in body
        assert "at=" in body
        assert "testRpc" in body


def test_build_url():
    """Test building batchexecute URL."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="test_token", session_id="test_sid")
        url = client._build_url("testRpc", "/notebook/123")
        assert "rpcids=testRpc" in url
        assert "source-path=" in url
        assert "f.sid=test_sid" in url


def test_get_httpx_cookies_from_dict():
    """Test converting dict cookies to httpx.Cookies."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={"SID": "abc123"}, csrf_token="token")
        cookies = client._get_httpx_cookies()
        # Should have cookies for both domains
        assert cookies.get("SID", domain=".google.com") == "abc123"
        assert cookies.get("SID", domain=".googleusercontent.com") == "abc123"


def test_get_httpx_cookies_from_list():
    """Test converting list of cookie dicts to httpx.Cookies."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        cookie_list = [{"name": "SID", "value": "abc123", "domain": ".google.com", "path": "/"}]
        client = BaseClient(cookies=cookie_list, csrf_token="token")
        cookies = client._get_httpx_cookies()
        assert cookies.get("SID", domain=".google.com") == "abc123"
        # Should also duplicate to googleusercontent.com
        assert cookies.get("SID", domain=".googleusercontent.com") == "abc123"


def test_parse_response():
    """Test parsing batchexecute response."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        # Simulate a typical batchexecute response
        response_text = """)]}'
42
[["wrb.fr","testRpc","{\\"data\\":\\"value\\"}"]]
"""
        result = client._parse_response(response_text)
        assert len(result) == 1
        assert result[0][0][0] == "wrb.fr"
        assert result[0][0][1] == "testRpc"


def test_extract_rpc_result():
    """Test extracting RPC result from parsed response."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        parsed = [[["wrb.fr", "testRpc", '{"status": "ok"}']]]
        result = client._extract_rpc_result(parsed, "testRpc")
        assert result == {"status": "ok"}


def test_extract_rpc_result_raises_rpc_error_on_transient():
    """Issue #98: structured API error in item[5] should raise RPCError."""
    from notebooklm_tools.core.base import BaseClient
    from notebooklm_tools.core.errors import RPCError

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        # Real failing deep response from Issue #98
        parsed = [
            [
                [
                    "wrb.fr",
                    "QA9ei",
                    None,
                    None,
                    None,
                    [
                        3,
                        None,
                        [
                            [
                                "type.googleapis.com/google.internal.labs.tailwind.orchestration.v1.DeepResearchErrorDetail",
                                [4],
                            ]
                        ],
                    ],
                    "generic",
                ]
            ]
        ]

        with pytest.raises(RPCError) as exc_info:
            client._extract_rpc_result(parsed, "QA9ei")

        assert exc_info.value.error_code == 3
        assert "DeepResearchErrorDetail" in exc_info.value.detail_type
        assert exc_info.value.detail_data == [4]


def test_extract_rpc_result_auth_error_still_works():
    """Auth errors (code 16) should still raise AuthenticationError, not RPCError."""
    from notebooklm_tools.core.base import BaseClient
    from notebooklm_tools.core.errors import ClientAuthenticationError

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        parsed = [[["wrb.fr", "testRpc", None, None, None, [16], "generic"]]]

        with pytest.raises(ClientAuthenticationError):
            client._extract_rpc_result(parsed, "testRpc")


def test_extract_rpc_result_unknown_error_code():
    """Unknown error codes should still raise RPCError with the code."""
    from notebooklm_tools.core.base import BaseClient
    from notebooklm_tools.core.errors import RPCError

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        parsed = [[["wrb.fr", "testRpc", None, None, None, [7], "generic"]]]

        with pytest.raises(RPCError) as exc_info:
            client._extract_rpc_result(parsed, "testRpc")

        assert exc_info.value.error_code == 7


def test_context_manager():
    """Test BaseClient as context manager."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        with BaseClient(cookies={}, csrf_token="token") as client:
            assert client is not None
        # After exiting, client should be closed
        assert client._client is None


def test_close():
    """Test explicit close."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")
        # Create but don't use _client
        client._client = MagicMock()
        client.close()
        assert client._client is None


def test_update_cached_tokens_persists_refreshed_cookies():
    """Rotated cookies must be cached with the refreshed request tokens."""
    from notebooklm_tools.core.auth import AuthTokens
    from notebooklm_tools.core.base import BaseClient

    cached = AuthTokens(
        cookies={"SID": "old"},
        csrf_token="old-csrf",
        session_id="old-session",
    )

    with (
        patch.object(BaseClient, "_refresh_auth_tokens"),
        patch("notebooklm_tools.core.auth.load_cached_tokens", return_value=cached),
        patch("notebooklm_tools.core.auth.save_tokens_to_cache") as mock_save,
    ):
        client = BaseClient(
            cookies={"SID": "rotated"},
            csrf_token="new-csrf",
            session_id="new-session",
        )
        client._update_cached_tokens()

    saved = mock_save.call_args.args[0]
    assert saved.cookies == {"SID": "rotated"}
    assert saved.csrf_token == "new-csrf"
    assert saved.session_id == "new-session"


def test_constants_available():
    """Test that RPC and API constants are available on BaseClient."""
    from notebooklm_tools.core.base import BaseClient

    # Check RPC IDs
    assert hasattr(BaseClient, "RPC_LIST_NOTEBOOKS")
    assert hasattr(BaseClient, "RPC_GET_NOTEBOOK")
    assert hasattr(BaseClient, "RPC_CREATE_STUDIO")

    # Check URLs
    assert hasattr(BaseClient, "BASE_URL")
    assert hasattr(BaseClient, "BATCHEXECUTE_URL")

    # Check constant re-exports
    assert hasattr(BaseClient, "STUDIO_TYPE_AUDIO")
    assert hasattr(BaseClient, "AUDIO_FORMAT_DEEP_DIVE")


def test_extract_rpc_result_raises_resource_exhausted_on_code_8():
    """Code 8 with UserDisplayableError should raise ResourceExhaustedError."""
    from notebooklm_tools.core.base import BaseClient
    from notebooklm_tools.core.errors import ResourceExhaustedError, RPCError

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        parsed = [
            [
                [
                    "wrb.fr",
                    "testRpc",
                    None,
                    None,
                    None,
                    [
                        8,
                        None,
                        [
                            [
                                "type.googleapis.com/google.internal.labs.tailwind.orchestration.v1.UserDisplayableError",
                                ["Too many requests, please try again later"],
                            ]
                        ],
                    ],
                    "generic",
                ]
            ]
        ]

        with pytest.raises(ResourceExhaustedError) as exc_info:
            client._extract_rpc_result(parsed, "testRpc")

        assert exc_info.value.error_code == 8
        assert "Too many requests" in str(exc_info.value)
        assert isinstance(exc_info.value, RPCError)


def test_extract_rpc_result_code_8_without_user_displayable():
    """Code 8 without UserDisplayableError still raises ResourceExhaustedError."""
    from notebooklm_tools.core.base import BaseClient
    from notebooklm_tools.core.errors import ResourceExhaustedError

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        parsed = [[["wrb.fr", "testRpc", None, None, None, [8], "generic"]]]

        with pytest.raises(ResourceExhaustedError) as exc_info:
            client._extract_rpc_result(parsed, "testRpc")

        assert exc_info.value.error_code == 8
        assert "RESOURCE_EXHAUSTED" in str(exc_info.value)


def test_extract_rpc_result_user_displayable_extracts_message():
    """UserDisplayableError detail_data text is included in error message for any code."""
    from notebooklm_tools.core.base import BaseClient
    from notebooklm_tools.core.errors import RPCError

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="token")

        parsed = [
            [
                [
                    "wrb.fr",
                    "testRpc",
                    None,
                    None,
                    None,
                    [
                        3,
                        None,
                        [
                            [
                                "type.googleapis.com/UserDisplayableError",
                                ["Notebook has too many sources"],
                            ]
                        ],
                    ],
                    "generic",
                ]
            ]
        ]

        with pytest.raises(RPCError) as exc_info:
            client._extract_rpc_result(parsed, "testRpc")

        assert "Notebook has too many sources" in str(exc_info.value)
        assert exc_info.value.error_code == 3


def test_extract_user_message_string():
    from notebooklm_tools.core.base import _extract_user_message

    assert _extract_user_message("Hello world") == "Hello world"


def test_extract_user_message_none():
    from notebooklm_tools.core.base import _extract_user_message

    assert _extract_user_message(None) == ""


def test_extract_user_message_nested_list():
    from notebooklm_tools.core.base import _extract_user_message

    result = _extract_user_message([None, ["Rate limit exceeded", 42], "try later"])
    assert "Rate limit exceeded" in result
    assert "try later" in result


def test_extract_user_message_empty_structures():
    from notebooklm_tools.core.base import _extract_user_message

    assert _extract_user_message([]) == ""
    assert _extract_user_message([None, [], None]) == ""


def test_extract_user_message_ints_skipped():
    from notebooklm_tools.core.base import _extract_user_message

    assert _extract_user_message([1, 2, 3]) == ""


def test_extract_user_message_deeply_nested():
    from notebooklm_tools.core.base import _extract_user_message

    data = [None, [None, [None, ["deeply nested message"]]]]
    assert _extract_user_message(data) == "deeply nested message"


def test_extract_user_message_depth_limit():
    from notebooklm_tools.core.base import _extract_user_message

    # Build a 25-level deep structure — should return "" due to depth guard
    data: Any = ["message"]
    for _ in range(25):
        data = [data]
    assert _extract_user_message(data) == ""


class TestBuildLabelPriority:
    """Test build label (bl) resolution priority in _build_url()."""

    def test_bl_uses_extracted_value(self):
        """Extracted build label is used when no env var override."""
        from notebooklm_tools.core.base import BaseClient

        with patch.object(BaseClient, "_refresh_auth_tokens"):
            client = BaseClient(
                cookies={},
                csrf_token="token",
                build_label="boq_labs-tailwind-frontend_20260219.16_p2",
            )
        url = client._build_url("testRpc")
        assert "boq_labs-tailwind-frontend_20260219.16_p2" in url

    def test_bl_env_var_overrides_extracted(self):
        """NOTEBOOKLM_BL env var takes precedence over extracted value."""
        import os

        from notebooklm_tools.core.base import BaseClient

        with patch.object(BaseClient, "_refresh_auth_tokens"):
            client = BaseClient(
                cookies={},
                csrf_token="token",
                build_label="extracted_value",
            )
        with patch.dict(os.environ, {"NOTEBOOKLM_BL": "env_override_value"}):
            url = client._build_url("testRpc")
        assert "env_override_value" in url
        assert "extracted_value" not in url

    def test_bl_falls_back_to_hardcoded(self):
        """Falls back to hardcoded default when nothing else is available."""
        from notebooklm_tools.core.base import BaseClient

        with patch.object(BaseClient, "_refresh_auth_tokens"):
            client = BaseClient(cookies={}, csrf_token="token")
        url = client._build_url("testRpc")
        assert BaseClient._BL_FALLBACK in url

    def test_bl_stored_on_init(self):
        """build_label parameter is stored as _bl on the client."""
        from notebooklm_tools.core.base import BaseClient

        with patch.object(BaseClient, "_refresh_auth_tokens"):
            client = BaseClient(
                cookies={},
                csrf_token="token",
                build_label="test_bl_value",
            )
        assert client._bl == "test_bl_value"


def test_extract_present_rpc_ids():
    """_extract_present_rpc_ids returns every rpc_id present in a parsed response."""
    from notebooklm_tools.core.base import BaseClient

    with patch.object(BaseClient, "_refresh_auth_tokens"):
        client = BaseClient(cookies={}, csrf_token="t")

    parsed = [
        [["wrb.fr", "abc123", "[1,2]", None, None, None, "generic"]],
        [["wrb.fr", "def456", "[]", None, None, None, "generic"]],
        [["di", 42]],  # non-wrb.fr noise must be ignored
    ]
    assert client._extract_present_rpc_ids(parsed) == ["abc123", "def456"]
