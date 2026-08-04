"""Tests for OpenCode client support in `nlm setup add/remove/list`.

Verifies that the OpenCode integration correctly handles the different
config schema (uses "mcp" key instead of "mcpServers", command as array).
"""

import json
from pathlib import Path
from unittest.mock import patch

from notebooklm_tools.cli.commands.setup import (
    CLIENT_REGISTRY,
    MCP_SERVER_CMD,
    MCP_SERVER_NAME,
    OPENCODE_MCP_TIMEOUT_MS,
    _detect_tool,
    _is_already_configured,
    _opencode_config_path,
    _remove_single,
    _setup_opencode,
)


class TestOpenCodeRegistry:
    """Verify OpenCode is properly registered in CLIENT_REGISTRY."""

    def test_opencode_in_registry(self):
        assert "opencode" in CLIENT_REGISTRY

    def test_opencode_has_auto_setup(self):
        assert CLIENT_REGISTRY["opencode"]["has_auto_setup"] is True

    def test_opencode_name(self):
        assert CLIENT_REGISTRY["opencode"]["name"] == "OpenCode"


class TestOpenCodeConfigPath:
    """Verify config path resolution."""

    def test_config_path_is_global(self):
        path = _opencode_config_path()
        assert path == Path.home() / ".config" / "opencode" / "opencode.json"


class TestSetupOpenCode:
    """Test _setup_opencode() writes correct config format."""

    def test_creates_config_from_scratch(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            result = _setup_opencode()

        assert result is True
        config = json.loads(config_path.read_text())
        assert "mcp" in config
        assert MCP_SERVER_NAME in config["mcp"]
        assert "notebooklm" not in config["mcp"]
        entry = config["mcp"][MCP_SERVER_NAME]
        assert entry["type"] == "local"
        assert entry["command"] == [MCP_SERVER_CMD]
        assert entry["enabled"] is True
        assert entry["timeout"] == OPENCODE_MCP_TIMEOUT_MS

    def test_preserves_existing_config_keys(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        existing = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {"test": {}},
            "model": "test-model",
        }
        config_path.write_text(json.dumps(existing))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert config["$schema"] == "https://opencode.ai/config.json"
        assert config["provider"] == {"test": {}}
        assert config["model"] == "test-model"
        assert MCP_SERVER_NAME in config["mcp"]

    def test_skips_if_already_configured(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        existing = {"mcp": {"notebooklm": {"type": "local", "command": ["notebooklm-mcp"]}}}
        config_path.write_text(json.dumps(existing))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            result = _setup_opencode()

        assert result is True
        # Config should be unchanged (no double write)

    def test_uses_mcp_key_not_mcpservers(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert "mcpServers" not in config
        assert "mcp" in config

    def test_command_is_array_not_string(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        command = config["mcp"][MCP_SERVER_NAME]["command"]
        assert isinstance(command, list)
        assert command == [MCP_SERVER_CMD]


class TestIsAlreadyConfigured:
    """Test _is_already_configured() for OpenCode."""

    def test_detects_notebooklm_key(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config_path.write_text(
            json.dumps({"mcp": {"notebooklm": {"type": "local", "command": [MCP_SERVER_CMD]}}})
        )
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("opencode") is True

    def test_detects_notebooklm_mcp_key(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config_path.write_text(
            json.dumps({"mcp": {"notebooklm-mcp": {"type": "local", "command": [MCP_SERVER_CMD]}}})
        )
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("opencode") is True

    def test_returns_false_when_not_configured(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config_path.write_text(json.dumps({"mcp": {}}))
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("opencode") is False

    def test_returns_false_when_no_config_file(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            assert _is_already_configured("opencode") is False


class TestDetectTool:
    """Test _detect_tool() for OpenCode."""

    def test_detects_via_which(self):
        with patch("shutil.which", return_value="/usr/bin/opencode"):
            assert _detect_tool("opencode") is True

    def test_detects_via_config_file(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config_path.write_text("{}")
        with (
            patch("shutil.which", return_value=None),
            patch(
                "notebooklm_tools.cli.commands.setup._opencode_config_path",
                return_value=config_path,
            ),
        ):
            assert _detect_tool("opencode") is True

    def test_not_detected_when_absent(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        with (
            patch("shutil.which", return_value=None),
            patch(
                "notebooklm_tools.cli.commands.setup._opencode_config_path",
                return_value=config_path,
            ),
        ):
            assert _detect_tool("opencode") is False


class TestRemoveOpenCode:
    """Test _remove_single() for OpenCode."""

    def test_removes_notebooklm_entry(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config = {
            "model": "test",
            "mcp": {
                MCP_SERVER_NAME: {"type": "local", "command": ["notebooklm-mcp"]},
                "other-server": {"type": "local", "command": ["other"]},
            },
        }
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            result = _remove_single("opencode")

        assert result is True
        updated = json.loads(config_path.read_text())
        assert MCP_SERVER_NAME not in updated["mcp"]
        assert "other-server" in updated["mcp"]
        assert updated["model"] == "test"

    def test_removes_notebooklm_mcp_entry(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config = {"mcp": {"notebooklm-mcp": {"type": "local", "command": [MCP_SERVER_CMD]}}}
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            result = _remove_single("opencode")

        assert result is True
        updated = json.loads(config_path.read_text())
        assert "notebooklm-mcp" not in updated["mcp"]

    def test_returns_false_when_not_configured(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        config_path.write_text(json.dumps({"mcp": {}}))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            result = _remove_single("opencode")

        assert result is False

    def test_returns_false_when_no_config_file(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            result = _remove_single("opencode")

        assert result is False


class TestOpenCodeTimeout:
    """Test MCP timeout configuration for OpenCode."""

    def test_sets_experimental_mcp_timeout(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert config["experimental"]["mcp_timeout"] == OPENCODE_MCP_TIMEOUT_MS

    def test_sets_per_server_timeout(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert config["mcp"][MCP_SERVER_NAME]["timeout"] == OPENCODE_MCP_TIMEOUT_MS

    def test_preserves_existing_experimental_mcp_timeout(self, tmp_path):
        """If user set a custom mcp_timeout, don't overwrite it."""
        config_path = tmp_path / "opencode.json"
        existing = {"experimental": {"mcp_timeout": 600_000}}
        config_path.write_text(json.dumps(existing))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert config["experimental"]["mcp_timeout"] == 600_000

    def test_preserves_other_experimental_keys(self, tmp_path):
        config_path = tmp_path / "opencode.json"
        existing = {"experimental": {"some_flag": True}}
        config_path.write_text(json.dumps(existing))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert config["experimental"]["some_flag"] is True
        assert config["experimental"]["mcp_timeout"] == OPENCODE_MCP_TIMEOUT_MS

    def test_adds_timeout_when_already_configured(self, tmp_path):
        """Even if server entry exists, ensure timeout is set."""
        config_path = tmp_path / "opencode.json"
        existing = {"mcp": {MCP_SERVER_NAME: {"type": "local", "command": ["notebooklm-mcp"]}}}
        config_path.write_text(json.dumps(existing))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _setup_opencode()

        config = json.loads(config_path.read_text())
        assert config["experimental"]["mcp_timeout"] == OPENCODE_MCP_TIMEOUT_MS

    def test_remove_cleans_experimental_timeout_when_no_servers(self, tmp_path):
        """Remove should clean up experimental.mcp_timeout when no MCP servers left."""
        config_path = tmp_path / "opencode.json"
        config = {
            "mcp": {MCP_SERVER_NAME: {"type": "local", "command": [MCP_SERVER_CMD]}},
            "experimental": {"mcp_timeout": OPENCODE_MCP_TIMEOUT_MS},
        }
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _remove_single("opencode")

        updated = json.loads(config_path.read_text())
        assert "experimental" not in updated

    def test_remove_keeps_experimental_timeout_when_other_servers(self, tmp_path):
        """Remove should keep experimental.mcp_timeout if other MCP servers remain."""
        config_path = tmp_path / "opencode.json"
        config = {
            "mcp": {
                MCP_SERVER_NAME: {"type": "local", "command": [MCP_SERVER_CMD]},
                "other-server": {"type": "local", "command": ["other"]},
            },
            "experimental": {"mcp_timeout": OPENCODE_MCP_TIMEOUT_MS},
        }
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _remove_single("opencode")

        updated = json.loads(config_path.read_text())
        assert updated["experimental"]["mcp_timeout"] == OPENCODE_MCP_TIMEOUT_MS

    def test_remove_keeps_other_experimental_keys(self, tmp_path):
        """Remove should only clean mcp_timeout, not other experimental keys."""
        config_path = tmp_path / "opencode.json"
        config = {
            "mcp": {MCP_SERVER_NAME: {"type": "local", "command": [MCP_SERVER_CMD]}},
            "experimental": {
                "mcp_timeout": OPENCODE_MCP_TIMEOUT_MS,
                "other_flag": True,
            },
        }
        config_path.write_text(json.dumps(config))

        with patch(
            "notebooklm_tools.cli.commands.setup._opencode_config_path",
            return_value=config_path,
        ):
            _remove_single("opencode")

        updated = json.loads(config_path.read_text())
        assert "mcp_timeout" not in updated["experimental"]
        assert updated["experimental"]["other_flag"] is True
