"""Setup commands report invalid configs without replacing their contents."""

import json

import pytest
from rich.console import Console
from typer.testing import CliRunner

from notebooklm_tools.cli.commands import setup


@pytest.mark.parametrize("action", ["add", "remove"])
@pytest.mark.parametrize("original", ['{"mcpServers": {,}', '["not an object"]'])
def test_setup_command_reports_parse_error(tmp_path, monkeypatch, action, original):
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(setup, "console", Console(width=240))
    monkeypatch.setattr(setup, "_antigravity_config_path", lambda: config_path)

    result = CliRunner().invoke(setup.app, [action, "antigravity"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert f"Cannot parse {config_path}" in result.output
    assert "fix or remove it before" in result.output
    assert "Traceback" not in result.output
    assert config_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("action", ["add", "remove"])
def test_setup_all_reports_parse_error(tmp_path, monkeypatch, action):
    config_path = tmp_path / "mcp_config.json"
    original = '{"mcpServers": {,}'
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(setup, "console", Console(width=240))

    def read_invalid_config():
        setup._read_json_config(config_path)

    monkeypatch.setattr(
        setup, f"_{'setup' if action == 'add' else 'remove'}_all", read_invalid_config
    )

    result = CliRunner().invoke(setup.app, [action, "all"])

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert f"Cannot parse {config_path}" in result.output
    assert "Traceback" not in result.output
    assert config_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("original", ["", "   \n\t  "], ids=["empty", "whitespace"])
def test_setup_add_initializes_blank_config(tmp_path, monkeypatch, original):
    config_path = tmp_path / "mcp_config.json"
    config_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(setup, "_antigravity_config_path", lambda: config_path)
    monkeypatch.setattr(setup, "_find_mcp_server_path", lambda: "/bin/notebooklm-mcp")

    result = CliRunner().invoke(setup.app, ["add", "antigravity"])

    assert result.exit_code == 0, result.output
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["mcpServers"][setup.MCP_SERVER_NAME]["command"] == "/bin/notebooklm-mcp"
