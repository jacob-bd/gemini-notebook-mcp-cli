"""Tests for the Gemini Notebook MCP branding contract."""

from pathlib import Path

from notebooklm_tools.cli.commands.setup import (
    MCP_SERVER_CMD,
    MCP_SERVER_NAME,
    _add_mcp_server,
    _add_vscode_mcp_server,
)
from notebooklm_tools.mcp.server import mcp


def test_json_mcp_setup_uses_gemini_notebook_server_name():
    config = {}

    _add_mcp_server(config)

    assert MCP_SERVER_NAME == "gemini-notebook-mcp"
    assert config["mcpServers"][MCP_SERVER_NAME]["command"] == MCP_SERVER_CMD


def test_vscode_mcp_setup_uses_gemini_notebook_server_name():
    config = {}

    _add_vscode_mcp_server(config)

    assert list(config["servers"]) == [MCP_SERVER_NAME]


def test_bundled_skill_uses_gemini_notebook_mcp_namespace():
    skill_path = Path("src/notebooklm_tools/data/SKILL.md")
    content = skill_path.read_text(encoding="utf-8")

    assert "mcp__gemini-notebook-mcp__" in content
    assert "mcp__notebooklm-mcp__" not in content


def test_mcp_server_uses_gemini_notebook_branding():
    assert mcp.name == MCP_SERVER_NAME
