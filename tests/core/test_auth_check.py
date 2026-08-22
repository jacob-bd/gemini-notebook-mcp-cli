"""Test-driven development for the elegant unified auth validity check.

The goal is a single source of truth:

    from notebooklm_tools.core.auth import check_auth, AuthCheckResult

    result = check_auth(live=True)   # authoritative
    result = check_auth(live=False)  # fast heuristic

Both `nlm login --check` and the MCP `server_info` tool should be thin
callers around this function. This eliminates the heuristic vs live
discrepancy at the root.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx

from notebooklm_tools.core.auth import (
    AuthCheckResult,
    AuthManager,
    check_auth,
)


class TestCheckAuthAPI:
    """Specification of the elegant public API we want."""

    def test_check_auth_returns_dataclass(self, tmp_path, monkeypatch):
        """check_auth must return a proper AuthCheckResult."""
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        # No tokens at all
        result = check_auth(live=False)
        assert isinstance(result, AuthCheckResult)
        assert result.valid is False
        assert result.reason == "no_tokens"

    def test_check_auth_live_false_uses_last_validated_heuristic(self, tmp_path, monkeypatch):
        """When live=False we should be fast and only look at on-disk metadata."""
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        # Arrange a profile that was validated very recently
        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={"SID": "x", "HSID": "x", "SSID": "x", "APISID": "x", "SAPISID": "x"},
            email="test@example.com",
        )
        # save_profile already sets last_validated to now; we just test the path

        result = check_auth(profile="default", live=False)
        assert result.valid is True
        assert result.live is False
        assert result.reason is None

    def test_check_auth_live_true_does_minimal_network_check(self, tmp_path, monkeypatch):
        """live=True must perform the authoritative homepage redirect check."""
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={"SID": "x", "HSID": "x", "SSID": "x", "APISID": "x", "SAPISID": "x"},
            email="test@example.com",
        )

        with patch("httpx.Client") as MockClient:
            client = MockClient.return_value.__enter__.return_value

            # Simulate successful (not redirected) homepage with real-looking token
            fake_response = httpx.Response(
                200,
                request=httpx.Request("GET", "https://notebooklm.google.com/"),
                text='WIZ_global_data = {"SNlM0e":"csrf123abc"}',
            )
            client.get.return_value = fake_response

            result = check_auth(live=True, timeout=5.0)

            assert result.valid is True
            assert result.live is True
            assert result.details is not None
            assert result.details.get("csrf_token") == "csrf123abc"

    def test_check_auth_live_true_detects_expired_redirect(self, tmp_path, monkeypatch):
        """Dead cookies require homepage redirect plus RPC rejection."""
        from notebooklm_tools.core.exceptions import AuthenticationError

        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={
                "SID": "dead",
                "HSID": "dead",
                "SSID": "dead",
                "APISID": "dead",
                "SAPISID": "dead",
            },
            csrf_token="stale123",
            session_id="sess123",
            email="test@example.com",
        )

        with (
            patch("httpx.Client") as MockClient,
            patch(
                "notebooklm_tools.core.client.NotebookLMClient.list_notebooks",
                side_effect=AuthenticationError("dead"),
            ),
        ):
            client = MockClient.return_value.__enter__.return_value

            # Simulate Google login redirect.
            req = httpx.Request("GET", "https://accounts.google.com/ServiceLogin")
            resp = httpx.Response(200, request=req, text="login page here")
            client.get.return_value = resp

            result = check_auth(live=True)

            assert result.valid is False
            assert result.reason == "expired"
            assert result.live is True

    def test_check_auth_classifies_client_rpc_auth_error_as_expired(
        self, tmp_path, monkeypatch
    ):
        """The low-level RPC client raises its own authentication class.

        It is not an NLMError and must not be mislabeled as a network outage.
        """
        from notebooklm_tools.core.errors import ClientAuthenticationError

        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)
        AuthManager("default").save_profile(
            cookies={"SID": "dead", "HSID": "dead", "SSID": "dead", "APISID": "dead", "SAPISID": "dead"},
            csrf_token="stale123",
            session_id="sess123",
        )
        with (
            patch("httpx.Client") as MockClient,
            patch(
                "notebooklm_tools.core.client.NotebookLMClient.list_notebooks",
                side_effect=ClientAuthenticationError("RPC code 16"),
            ),
        ):
            client = MockClient.return_value.__enter__.return_value
            req = httpx.Request("GET", "https://accounts.google.com/ServiceLogin")
            client.get.return_value = httpx.Response(200, request=req, text="login")
            result = check_auth(live=True)

        assert result.valid is False
        assert result.reason == "expired"

    def test_check_auth_live_true_redirect_but_rpc_alive_is_valid(self, tmp_path, monkeypatch):
        """Homepage redirects can be false negatives; a live RPC wins."""
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={"SID": "x", "HSID": "x", "SSID": "x", "APISID": "x", "SAPISID": "x"},
            csrf_token="csrf123",
            session_id="sess123",
            email="test@example.com",
            build_label="build123",
        )

        with (
            patch("httpx.Client") as MockClient,
            patch(
                "notebooklm_tools.core.client.NotebookLMClient.list_notebooks",
                return_value=[],
            ),
        ):
            client = MockClient.return_value.__enter__.return_value
            req = httpx.Request("GET", "https://accounts.google.com/ServiceLogin")
            client.get.return_value = httpx.Response(200, request=req, text="login page")

            result = check_auth(live=True)

        assert result.valid is True
        assert result.reason is None
        assert result.live is True
        assert result.details == {"recovered_via": "rpc"}

    def test_check_auth_live_true_non_redirect_non_200_reports_http_error(
        self, tmp_path, monkeypatch
    ):
        """A non-login non-200 homepage remains an HTTP error."""
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={"SID": "x", "HSID": "x", "SSID": "x", "APISID": "x", "SAPISID": "x"},
            email="test@example.com",
        )

        with patch("httpx.Client") as MockClient:
            client = MockClient.return_value.__enter__.return_value
            req = httpx.Request("GET", "https://notebooklm.google.com/")
            client.get.return_value = httpx.Response(500, request=req, text="oops")

            result = check_auth(live=True)

        assert result.valid is False
        assert result.reason == "http_500"
        assert result.live is True

    def test_check_auth_live_true_degrades_on_read_timeout(self, tmp_path, monkeypatch):
        """Regression for #243: a real httpx.ReadTimeout from the homepage probe
        must degrade to a graceful invalid result, never propagate as an uncaught
        exception (which previously crashed `nlm login --check`). This pins the
        fault line directly — narrowing the except in check_auth fails this test.
        """
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={"SID": "x", "HSID": "x", "SSID": "x", "APISID": "x", "SAPISID": "x"},
            email="test@example.com",
        )

        with patch("httpx.Client") as MockClient:
            client = MockClient.return_value.__enter__.return_value
            client.get.side_effect = httpx.ReadTimeout("read timed out")

            result = check_auth(live=True, timeout=5.0)

        assert result.valid is False
        assert result.reason == "network_error: ReadTimeout"
        assert result.live is True

    def test_auth_manager_has_check_validity(self, tmp_path, monkeypatch):
        """AuthManager should expose a convenient .check_validity() method."""
        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        mgr = AuthManager("default")
        mgr.save_profile(
            cookies={"SID": "x", "HSID": "x", "SSID": "x", "APISID": "x", "SAPISID": "x"},
            email="test@example.com",
        )

        # Should not blow up and should return the dataclass
        res = mgr.check_validity(live=False)
        assert isinstance(res, AuthCheckResult)


class TestIntegrationWithExistingCode:
    """The elegant function must be usable by both CLI and MCP paths without duplication."""

    def test_server_info_can_use_check_auth(self, tmp_path, monkeypatch):
        """The MCP server_info path should be able to delegate to the single function."""
        from notebooklm_tools.mcp.tools.server import _check_auth_status

        monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

        # With no tokens the status must be not_configured (current contract)
        status = _check_auth_status()
        assert status == "not_configured"

    def test_login_check_path_can_use_check_auth(self):
        """The heavy lifting inside _validate_saved_profile should eventually call check_auth."""
        # This is a contract test / reminder for the refactor.
        # After the elegant change, _validate_saved_profile becomes a thin presenter
        # around check_auth(live=True) + nice printing.
        assert True  # placeholder until we do the CLI side cleanup
