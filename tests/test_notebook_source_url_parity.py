"""Offline CLI/MCP parity for notebook source metadata."""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from notebooklm_tools.cli.commands.notebook import app
from notebooklm_tools.core import constants
from notebooklm_tools.core.sources import source_url_from_metadata
from notebooklm_tools.mcp.tools.notebooks import notebook_get


@pytest.mark.parametrize(
    ("source_type", "slot", "value", "expected"),
    [
        (
            constants.SOURCE_TYPE_WEB_PAGE,
            7,
            "https://example.org/source",
            "https://example.org/source",
        ),
        (
            constants.SOURCE_TYPE_WEB_PAGE,
            7,
            " http://example.org/source ",
            "http://example.org/source",
        ),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "javascript:alert(1)", None),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "data:text/html,test", None),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "https://", None),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "https://example.org/a\nnext", None),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "   ", None),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "https://[broken", None),
        (
            constants.SOURCE_TYPE_YOUTUBE,
            5,
            "https://www.youtube.com/watch?v=example",
            "https://www.youtube.com/watch?v=example",
        ),
        (constants.SOURCE_TYPE_WORD_DOC, 7, "https://example.org/unverified", None),
        (None, 7, "https://example.org/unverified", None),
    ],
)
def test_source_url_type_specific_validation(source_type, slot, value, expected):
    metadata = [None] * 10
    metadata[slot] = [value]
    assert source_url_from_metadata(source_type, metadata) == expected


def test_youtube_uses_its_own_slot_not_web_slot():
    metadata = [None] * 10
    metadata[5] = ["https://www.youtube.com/watch?v=verified"]
    metadata[7] = ["https://example.org/unrelated"]
    assert source_url_from_metadata(constants.SOURCE_TYPE_YOUTUBE, metadata) == (
        "https://www.youtube.com/watch?v=verified"
    )


@pytest.mark.parametrize(
    ("source_type", "slot", "value", "expected"),
    [
        (
            constants.SOURCE_TYPE_YOUTUBE,
            5,
            "https://www.youtube.com/watch?v=test",
            "https://www.youtube.com/watch?v=test",
        ),
        (
            constants.SOURCE_TYPE_PDF,
            7,
            "https://example.org/manual.pdf",
            "https://example.org/manual.pdf",
        ),
        (constants.SOURCE_TYPE_WEB_PAGE, 7, "javascript:alert(1)", None),
        (constants.SOURCE_TYPE_WORD_DOC, 7, "https://example.org/false-drive", None),
        (None, 7, "https://example.org/untyped", None),
    ],
)
def test_notebook_get_source_url_parity_for_other_types(source_type, slot, value, expected):
    client = MagicMock()
    client.__enter__.return_value = client
    metadata = [None] * 10
    metadata[4] = source_type
    metadata[slot] = [value]
    client.get_notebook.return_value = [["Notebook", [[["source"], "Item", metadata]], "nb-1"]]
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
        == [{"id": "source", "title": "Item", "url": expected}]
    )


def test_notebook_get_source_url_parity():
    client = MagicMock()
    client.__enter__.return_value = client
    metadata = [None] * 8
    metadata[4] = constants.SOURCE_TYPE_WEB_PAGE
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
