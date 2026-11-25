"""Offline CLI/MCP parity for notebook source metadata."""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from notebooklm_tools.cli.commands.notebook import app
from notebooklm_tools.mcp.tools.notebooks import notebook_get


def test_notebook_get_source_url_parity():
    client = MagicMock()
    client.__enter__.return_value = client
    metadata = [None] * 8
    metadata[7] = ["https://example.org/source"]
    client.get_notebook.return_value = [["Notebook", [[["source"], "Web", metadata]], "nb-1"]]
    alias = MagicMock()
    alias.resolve.side_effect = lambda value: value
    with (
        patch("notebooklm_tools.cli.commands.notebook.get_alias_manager", return_value=alias),
        patch("notebooklm_tools.cli.commands.notebook.get_client", return_value=client),
        patch("notebooklm_tools.mcp.tools.notebooks.get_client", return_value=client),
    ):
        cli = CliRunner().invoke(app, ["get", "nb-1", "--json"])
        mcp = notebook_get("nb-1")

    assert cli.exit_code == 0, cli.output
    assert mcp["status"] == "success"
    assert (
        json.loads(cli.output)["sources"]
        == mcp["sources"]
        == [{"id": "source", "title": "Web", "url": "https://example.org/source"}]
    )
