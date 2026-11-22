"""Tests for Claude Desktop support in ``nlm setup add/remove/list``."""

import json
import os
from pathlib import Path
from types import SimpleNamespace
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
    _without_own_process_ancestry,
    app,
)


def _msix_layout(tmp_path, package_name="Claude_pzs8sxrjxfjjc"):
    """Create a Claude Desktop MSIX package folder and return its paths."""
    local_app_data = tmp_path / "LocalAppData"
    legacy_dir = local_app_data / "Packages" / package_name / "LocalCache" / "Roaming" / "Claude"
    legacy_dir.mkdir(parents=True)
    return local_app_data, legacy_dir


def _windows_env(local_app_data, tmp_path):
    return patch.dict(
        os.environ,
        {
            "APPDATA": str(tmp_path / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(local_app_data),
        },
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

    def test_windows_path_uses_shell_profile_when_path_home_is_unavailable(self, tmp_path):
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict(os.environ, {}, clear=True),
            patch("pathlib.Path.home", side_effect=RuntimeError("home unavailable")),
            patch(
                "notebooklm_tools.cli.commands.setup._windows_profile_dir_from_shell",
                return_value=tmp_path,
            ),
        ):
            path = _claude_desktop_config_path()

        assert path == tmp_path / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json"

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

    def test_windows_path_uses_migrated_claude_data_with_left_marker(self, tmp_path):
        local_app_data, legacy_dir = _msix_layout(tmp_path)
        family = "claude_pzs8sxrjxfjjc"
        migrated_dir = local_app_data / "Claude-Data" / family
        migrated_dir.mkdir(parents=True)
        (legacy_dir / f".user-data-left.{family}").write_text("")

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
        ):
            path = _claude_desktop_config_path()
        assert path == migrated_dir / "claude_desktop_config.json"

    def test_windows_path_ignores_empty_claude_data_folder(self, tmp_path):
        local_app_data, legacy_dir = _msix_layout(tmp_path)
        legacy_config = legacy_dir / "claude_desktop_config.json"
        legacy_config.write_text("{}")
        (local_app_data / "Claude-Data").mkdir(parents=True)

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
        ):
            path = _claude_desktop_config_path()
        assert path == legacy_config

    def test_windows_path_returns_to_legacy_folder_on_back_marker(self, tmp_path):
        local_app_data, legacy_dir = _msix_layout(tmp_path)
        family = "claude_pzs8sxrjxfjjc"
        (local_app_data / "Claude-Data" / family).mkdir(parents=True)
        (legacy_dir / f".user-data-back.{family}").write_text("")

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
        ):
            path = _claude_desktop_config_path()
        assert path == legacy_dir / "claude_desktop_config.json"

    def test_windows_path_uses_migrated_dir_without_markers(self, tmp_path):
        local_app_data, _ = _msix_layout(tmp_path)
        migrated_dir = local_app_data / "Claude-Data" / "claude_pzs8sxrjxfjjc"
        migrated_dir.mkdir(parents=True)

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
        ):
            path = _claude_desktop_config_path()
        assert path == migrated_dir / "claude_desktop_config.json"

    def test_windows_path_lowercases_mixed_case_package_folder(self, tmp_path):
        local_app_data, _ = _msix_layout(tmp_path, package_name="Claude_PZS8SXRJXFJJC")
        migrated_dir = local_app_data / "Claude-Data" / "claude_pzs8sxrjxfjjc"
        migrated_dir.mkdir(parents=True)

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
        ):
            path = _claude_desktop_config_path()
        assert path == migrated_dir / "claude_desktop_config.json"

    def test_windows_detects_regular_profile_on_migrated_layout(self, tmp_path):
        local_app_data, _ = _msix_layout(tmp_path)
        migrated_dir = local_app_data / "Claude-Data" / "claude_pzs8sxrjxfjjc"
        migrated_dir.mkdir(parents=True)

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
        ):
            paths = _claude_desktop_profile_paths()
        assert paths.get("regular") == migrated_dir / "claude_desktop_config.json"

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

    def test_own_nlm_invocation_is_not_treated_as_desktop(self):
        ps_output = (
            "    1     0 /sbin/launchd\n"
            "  500     1 /bin/zsh -c nlm setup add claude-desktop\n"
            "  501   500 /Users/test/.local/bin/python3 /Users/test/.local/bin/nlm "
            "setup add claude-desktop\n"
            "  502   501 ps -axo pid=,ppid=,command=\n"
        )
        process_list = _without_own_process_ancestry(ps_output, own_pid=501)
        assert "claude-desktop" not in process_list
        assert _claude_desktop_profile_is_running("regular", process_list=process_list) is False

    def test_keeps_unrelated_desktop_and_desktop_ancestor(self):
        ps_output = (
            "    1     0 /sbin/launchd\n"
            "  400     1 /Applications/Claude.app/Contents/MacOS/Claude\n"
            "  500   400 /bin/zsh -c nlm setup add claude-desktop\n"
            "  501   500 /Users/test/.local/bin/python3 /Users/test/.local/bin/nlm "
            "setup add claude-desktop\n"
            "  600     1 /usr/bin/claude-desktop --no-sandbox\n"
        )
        process_list = _without_own_process_ancestry(ps_output, own_pid=501)
        assert process_list.splitlines() == [
            "/Applications/Claude.app/Contents/MacOS/Claude",
            "/usr/bin/claude-desktop --no-sandbox",
        ]
        assert _claude_desktop_profile_is_running("regular", process_list=process_list) is True


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
                "notebooklm_tools.cli.commands.setup.questionary.select",
                return_value=SimpleNamespace(ask=lambda: "both"),
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

    def test_setup_add_and_list_target_migrated_config(self, tmp_path):
        local_app_data, legacy_dir = _msix_layout(tmp_path)
        migrated_dir = local_app_data / "Claude-Data" / "claude_pzs8sxrjxfjjc"
        migrated_dir.mkdir(parents=True)
        migrated_config = migrated_dir / "claude_desktop_config.json"

        def regular_row(output: str) -> str:
            # The table wraps "(regular)" onto a second line at 80 columns;
            # the status cell sits on the first line of the row.
            rows = [line for line in output.splitlines() if "Claude Desktop" in line]
            assert len(rows) == 1, output
            return rows[0]

        with (
            _windows_env(local_app_data, tmp_path),
            patch("platform.system", return_value="Windows"),
            patch(
                "notebooklm_tools.cli.commands.setup._find_mcp_server_path",
                return_value="/usr/local/bin/notebooklm-mcp",
            ),
            patch(
                "notebooklm_tools.cli.commands.setup._claude_desktop_profile_is_running",
                return_value=False,
            ),
        ):
            before = CliRunner().invoke(app, ["list"])
            add_result = CliRunner().invoke(app, ["add", "claude-desktop"])
            after = CliRunner().invoke(app, ["list"])

        assert before.exit_code == 0, before.stdout
        assert "✓" not in regular_row(before.stdout)

        assert add_result.exit_code == 0, add_result.stdout
        assert MCP_SERVER_NAME in json.loads(migrated_config.read_text())["mcpServers"]
        assert not (legacy_dir / "claude_desktop_config.json").exists()

        # `list` can only report ✓ by reading the migrated file; the legacy
        # config was never written.
        assert after.exit_code == 0, after.stdout
        assert "✓" in regular_row(after.stdout)

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


def test_relay_session_without_3p_process_marker_counts_as_3p_running(monkeypatch):
    from notebooklm_tools.cli.commands import setup

    main_only = "  42     1 /Applications/Claude.app/Contents/MacOS/Claude\n"
    monkeypatch.setattr(setup, "_claude_desktop_process_list", lambda: main_only)
    monkeypatch.setattr(setup, "_claude_desktop_3p_session_active", lambda: True)
    assert setup._claude_desktop_profile_is_running("3p") is True
    assert setup._claude_desktop_profile_is_running("regular") is False

    monkeypatch.setattr(setup, "_claude_desktop_3p_session_active", lambda: False)
    assert setup._claude_desktop_profile_is_running("3p") is False
    assert setup._claude_desktop_profile_is_running("regular") is True
