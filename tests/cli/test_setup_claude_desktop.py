"""Tests for Claude Desktop support in ``nlm setup add/remove/list``."""

import json
import os
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from notebooklm_tools.cli.commands.setup import (
    CLIENT_REGISTRY,
    MCP_SERVER_CMD,
    MCP_SERVER_NAME,
    _claude_desktop_config_path,
    _claude_desktop_profile_is_running,
    _claude_desktop_profile_paths,
    _detect_tool,
    _is_already_configured,
    _remove_single,
    _setup_claude_desktop,
    app,
)


class TestClaudeDesktopRegistry:
    """Verify Claude Desktop is properly registered in CLIENT_REGISTRY."""

    def test_claude_desktop_in_registry(self):
        assert "claude-desktop" in CLIENT_REGISTRY

    def test_claude_desktop_has_auto_setup(self):
        assert CLIENT_REGISTRY["claude-desktop"]["has_auto_setup"] is True

    def test_claude_desktop_name(self):
        assert CLIENT_REGISTRY["claude-desktop"]["name"] == "Claude Desktop"


class TestClaudeDesktopConfigPath:
    """Verify platform-specific config path resolution."""

    def test_macos_path_defaults_to_third_party_profile(self, tmp_path):
        with (
            patch("platform.system", return_value="Darwin"),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            path = _claude_desktop_config_path()
        assert path == (
            tmp_path
            / "Library"
            / "Application Support"
            / "Claude-3p"
            / "claude_desktop_config.json"
        )

    def test_windows_path(self):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict("os.environ", {"APPDATA": "C:/Users/test/AppData/Roaming"}),
        ):
            path = _claude_desktop_config_path()
        assert (
            path == Path("C:/Users/test/AppData/Roaming") / "Claude" / "claude_desktop_config.json"
        )

    def test_windows_path_falls_back_when_appdata_is_missing(self):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(os.environ, {}, clear=True),
        ):
            path = _claude_desktop_config_path()
        assert path == Path.home() / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"

    def test_windows_path_uses_existing_msix_config(self, tmp_path):
        local_app_data = tmp_path / "LocalAppData"
        msix_config = (
            local_app_data
            / "Packages"
            / "Claude_pzs8sxrjxfjjc"
            / "LocalCache"
            / "Roaming"
            / "Claude"
            / "claude_desktop_config.json"
        )
        msix_config.parent.mkdir(parents=True)
        msix_config.write_text("{}")

        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(
                os.environ,
                {
                    "APPDATA": str(tmp_path / "AppData" / "Roaming"),
                    "LOCALAPPDATA": str(local_app_data),
                },
            ),
        ):
            path = _claude_desktop_config_path()
        assert path == msix_config

    def test_windows_path_uses_standard_path_when_msix_install_is_ambiguous(self, tmp_path):
        local_app_data = tmp_path / "LocalAppData"
        for package_name in ("Claude_first", "Claude_second"):
            (local_app_data / "Packages" / package_name).mkdir(parents=True)

        appdata = tmp_path / "AppData" / "Roaming"
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(
                os.environ,
                {"APPDATA": str(appdata), "LOCALAPPDATA": str(local_app_data)},
            ),
        ):
            path = _claude_desktop_config_path()
        assert path == appdata / "Claude" / "claude_desktop_config.json"

    def test_linux_path(self):
        with patch("platform.system", return_value="Linux"):
            path = _claude_desktop_config_path()
        assert path == Path.home() / ".config" / "Claude" / "claude_desktop_config.json"

    def test_macos_detects_only_existing_profiles(self, tmp_path):
        app_support = tmp_path / "Library" / "Application Support"
        third_party = app_support / "Claude-3p"
        third_party.mkdir(parents=True)

        with (
            patch("platform.system", return_value="Darwin"),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            paths = _claude_desktop_profile_paths()

        assert paths == {
            "3p": third_party / "claude_desktop_config.json",
        }

    def test_windows_detects_regular_and_3p_profiles(self, tmp_path):
        appdata = tmp_path / "AppData" / "Roaming"
        local_appdata = tmp_path / "AppData" / "Local"
        (appdata / "Claude").mkdir(parents=True)
        (local_appdata / "Claude-3p").mkdir(parents=True)

        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(
                os.environ,
                {"APPDATA": str(appdata), "LOCALAPPDATA": str(local_appdata)},
            ),
        ):
            paths = _claude_desktop_profile_paths()

        assert paths == {
            "regular": appdata / "Claude" / "claude_desktop_config.json",
            "3p": local_appdata / "Claude-3p" / "claude_desktop_config.json",
        }

    def test_linux_uses_xdg_config_home_for_3p_profile(self, tmp_path):
        xdg_config_home = tmp_path / "xdg"
        third_party = xdg_config_home / "Claude-3p"
        third_party.mkdir(parents=True)

        with (
            patch("platform.system", return_value="Linux"),
            patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg_config_home)}),
        ):
            paths = _claude_desktop_profile_paths()

        assert paths == {
            "3p": third_party / "claude_desktop_config.json",
        }

    def test_returns_no_profiles_when_claude_desktop_is_absent(self, tmp_path):
        with (
            patch("platform.system", return_value="Darwin"),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            paths = _claude_desktop_profile_paths()

        assert paths == {}


class TestClaudeDesktopProcessDetection:
    """Test profile-aware Claude Desktop process detection."""

    def test_empty_process_snapshot_means_no_profile_is_running(self):
        assert _claude_desktop_profile_is_running("3p", process_list="") is False

    def test_detects_relay_ai_3p_process_from_user_data_dir(self):
        process_list = (
            "/Applications/Claude.app/Contents/MacOS/Claude Helper "
            "--user-data-dir=/Users/test/Library/Application Support/Claude-3p\n"
        )
        assert _claude_desktop_profile_is_running("3p", process_list=process_list) is True
        assert _claude_desktop_profile_is_running("regular", process_list=process_list) is False

    def test_ignores_claude_crashpad_helper_after_desktop_quits(self):
        process_list = (
            "/Applications/Claude.app/Contents/Frameworks/Electron Framework.framework/"
            "Helpers/chrome_crashpad_handler "
            "--database=/Users/test/Library/Application Support/Claude-3p/Crashpad\n"
        )
        assert _claude_desktop_profile_is_running("3p", process_list=process_list) is False
        assert _claude_desktop_profile_is_running("regular", process_list=process_list) is False

    def test_does_not_treat_relay_ai_claude_code_as_desktop(self):
        process_list = "node /Users/test/bin/relay-ai claude --trace\n"
        assert _claude_desktop_profile_is_running("3p", process_list=process_list) is False
        assert _claude_desktop_profile_is_running("regular", process_list=process_list) is False


class TestSetupClaudeDesktop:
    """Test ``_setup_claude_desktop()`` writes the correct config format."""

    def test_creates_config_with_full_binary_path(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": config_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
        ):
            result = _setup_claude_desktop()

        assert result is True
        config = json.loads(config_path.read_text())
        assert MCP_SERVER_NAME in config["mcpServers"]
        assert "notebooklm-mcp" not in config["mcpServers"]
        entry = config["mcpServers"][MCP_SERVER_NAME]
        assert entry["command"] == "/usr/local/bin/notebooklm-mcp"
        assert entry["args"] == []

    def test_returns_false_without_writing_when_binary_is_not_on_path(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": config_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value=None,
            ),
        ):
            result = _setup_claude_desktop()

        assert result is False
        assert not config_path.exists()

    def test_preserves_existing_config_keys(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        existing = {
            "mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}},
            "coworkUserFilesPath": "/Users/test/Claude",
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(existing))

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": config_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
        ):
            _setup_claude_desktop()

        config = json.loads(config_path.read_text())
        assert config["coworkUserFilesPath"] == existing["coworkUserFilesPath"]
        assert "fetch" in config["mcpServers"]
        assert MCP_SERVER_NAME in config["mcpServers"]

    def test_skips_if_already_configured(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(
                {"mcpServers": {MCP_SERVER_NAME: {"command": "/usr/local/bin/notebooklm-mcp"}}}
            )
        )

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            result = _setup_claude_desktop()

        assert result is True

    def test_does_not_create_config_when_no_profile_is_detected(self, tmp_path):
        config_path = tmp_path / "Claude" / "claude_desktop_config.json"
        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
        ):
            result = _setup_claude_desktop()

        assert result is False
        assert not config_path.exists()

    def test_prompts_when_regular_and_3p_profiles_are_detected(self, tmp_path):
        regular_path = tmp_path / "regular" / "claude_desktop_config.json"
        third_party_path = tmp_path / "3p" / "claude_desktop_config.json"

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": regular_path, "3p": third_party_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
            patch(
                "notebooklm_tools.cli.commands.setup.Prompt.ask",
                return_value="3",
            ) as prompt,
        ):
            result = _setup_claude_desktop()

        assert result is True
        assert regular_path.exists()
        assert third_party_path.exists()
        prompt.assert_called_once()

    def test_accepts_explicit_profile_selection(self, tmp_path):
        regular_path = tmp_path / "regular" / "claude_desktop_config.json"
        third_party_path = tmp_path / "3p" / "claude_desktop_config.json"

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": regular_path, "3p": third_party_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_is_running",
                return_value=False,
                create=True,
            ),
        ):
            result = CliRunner().invoke(app, ["add", "claude-desktop", "--profile", "3p"])

        assert result.exit_code == 0, result.stdout
        assert third_party_path.exists()
        assert not regular_path.exists()

    def test_refuses_to_write_when_selected_profile_is_running(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"3p": config_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_is_running",
                return_value=True,
                create=True,
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                side_effect=AssertionError("running Claude must block before binary lookup"),
            ),
        ):
            result = _setup_claude_desktop(profile="3p")

        assert result is False
        assert not config_path.exists()


class TestIsAlreadyConfigured:
    """Test ``_is_already_configured()`` for Claude Desktop."""

    def test_detects_notebooklm_key(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"mcpServers": {"notebooklm": {"command": MCP_SERVER_CMD}}})
        )
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            assert _is_already_configured("claude-desktop") is True

    def test_detects_new_gemini_notebook_mcp_key(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps({"mcpServers": {MCP_SERVER_NAME: {"command": MCP_SERVER_CMD}}})
        )
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            assert _is_already_configured("claude-desktop") is True

    def test_returns_false_when_not_configured(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"mcpServers": {}}))
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            assert _is_already_configured("claude-desktop") is False

    def test_returns_false_when_no_config_file(self, tmp_path):
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={},
        ):
            assert _is_already_configured("claude-desktop") is False


class TestDetectTool:
    """Test ``_detect_tool()`` for Claude Desktop."""

    def test_detects_via_config_directory(self, tmp_path):
        config_path = tmp_path / "Claude" / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            assert _detect_tool("claude-desktop") is True

    def test_not_detected_when_absent(self, tmp_path):
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={},
        ):
            assert _detect_tool("claude-desktop") is False


class TestRemoveClaudeDesktop:
    """Test ``_remove_single()`` for Claude Desktop."""

    def test_prompts_and_removes_mcp_from_selected_profile(self, tmp_path):
        regular_path = tmp_path / "regular" / "claude_desktop_config.json"
        third_party_path = tmp_path / "3p" / "claude_desktop_config.json"
        regular_path.parent.mkdir(parents=True)
        third_party_path.parent.mkdir(parents=True)
        regular_path.write_text(
            json.dumps({"mcpServers": {"notebooklm-mcp": {"command": "notebooklm-mcp"}}})
        )
        third_party_path.write_text(json.dumps({"mcpServers": {}}))

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": regular_path, "3p": third_party_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup.Prompt.ask",
                return_value="1",
            ) as prompt,
        ):
            result = _remove_single("claude-desktop")

        assert result is True
        assert "notebooklm-mcp" not in json.loads(regular_path.read_text())["mcpServers"]
        assert json.loads(third_party_path.read_text()) == {"mcpServers": {}}
        prompt.assert_not_called()

    def test_only_offers_profiles_that_contain_our_mcp(self, tmp_path):
        regular_path = tmp_path / "regular" / "claude_desktop_config.json"
        third_party_path = tmp_path / "3p" / "claude_desktop_config.json"
        regular_path.parent.mkdir(parents=True)
        third_party_path.parent.mkdir(parents=True)
        regular_path.write_text(json.dumps({"mcpServers": {"fetch": {"command": "fetch"}}}))
        third_party_path.write_text(
            json.dumps({"mcpServers": {MCP_SERVER_NAME: {"command": MCP_SERVER_CMD}}})
        )

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": regular_path, "3p": third_party_path},
            ),
            patch("notebooklm_tools.cli.commands.setup.Prompt.ask") as prompt,
        ):
            result = _remove_single("claude-desktop")

        assert result is True
        assert json.loads(regular_path.read_text())["mcpServers"]["fetch"]
        assert MCP_SERVER_NAME not in json.loads(third_party_path.read_text())["mcpServers"]
        prompt.assert_not_called()

    def test_does_not_show_profiles_when_none_contains_our_mcp(self, tmp_path):
        regular_path = tmp_path / "regular" / "claude_desktop_config.json"
        third_party_path = tmp_path / "3p" / "claude_desktop_config.json"
        regular_path.parent.mkdir(parents=True)
        third_party_path.parent.mkdir(parents=True)
        regular_path.write_text(json.dumps({"mcpServers": {"fetch": {"command": "fetch"}}}))
        third_party_path.write_text(json.dumps({"mcpServers": {}}))

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"regular": regular_path, "3p": third_party_path},
            ),
            patch("notebooklm_tools.cli.commands.setup.Prompt.ask") as prompt,
        ):
            result = _remove_single("claude-desktop")

        assert result is False
        prompt.assert_not_called()

    def test_removes_notebooklm_entry(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config = {
            "coworkUserFilesPath": "/Users/test/Claude",
            "mcpServers": {
                MCP_SERVER_NAME: {"command": "/usr/local/bin/notebooklm-mcp", "args": []},
                "fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
            },
        }
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            result = _remove_single("claude-desktop")

        assert result is True
        updated = json.loads(config_path.read_text())
        assert MCP_SERVER_NAME not in updated["mcpServers"]
        assert "fetch" in updated["mcpServers"]
        assert updated["coworkUserFilesPath"] == config["coworkUserFilesPath"]

    def test_refuses_to_remove_when_selected_profile_is_running(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        original = {"mcpServers": {MCP_SERVER_NAME: {"command": MCP_SERVER_CMD}}}
        config_path.write_text(json.dumps(original))

        with (
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
                return_value={"3p": config_path},
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_is_running",
                return_value=True,
                create=True,
            ),
        ):
            result = _remove_single("claude-desktop", profile="3p")

        assert result is False
        assert json.loads(config_path.read_text()) == original

    def test_returns_false_when_not_configured(self, tmp_path):
        config_path = tmp_path / "claude_desktop_config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"mcpServers": {}}))

        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={"regular": config_path},
        ):
            result = _remove_single("claude-desktop")

        assert result is False

    def test_returns_false_when_no_config_file(self, tmp_path):
        with patch(
            "notebooklm_tools.cli.commands.setup._claude_desktop_profile_paths",
            return_value={},
        ):
            result = _remove_single("claude-desktop")

        assert result is False
