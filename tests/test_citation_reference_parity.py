"""Preserve native citation chunk IDs across offline query interfaces."""

import asyncio
import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from notebooklm_tools.cli.commands.notebook import app
from notebooklm_tools.core.conversation import ConversationMixin
from notebooklm_tools.mcp.tools.chat import notebook_query
from notebooklm_tools.services.chat import query


def _passage(chunk, source):
    return [
        chunk,
        [None, None, 0.75, [[None, 0, 5]], [], [[[source], "hash"]]],
    ]


def test_chunk_ids_preserve_citation_positions_and_omit_invalid_ids():
    data = ConversationMixin._extract_citation_data(
        [
            None,
            None,
            None,
            [
                _passage(["chunk-a"], "source-1"),
                None,
                _passage(["chunk-b"], "source-1"),
                _passage([False], "source-2"),
                _passage([], "source-2"),
            ],
        ]
    )

    assert data["citations"] == {1: "source-1", 3: "source-1", 4: "source-2", 5: "source-2"}
    assert data["sources_used"] == ["source-1", "source-2"]
    assert data["references"] == [
        {"source_id": "source-1", "citation_number": 1, "chunk_id": "chunk-a"},
        {"source_id": "source-1", "citation_number": 3, "chunk_id": "chunk-b"},
        {"source_id": "source-2", "citation_number": 4},
        {"source_id": "source-2", "citation_number": 5},
    ]


def test_opaque_chunk_ids_preserve_duplicates_and_skip_whitespace():
    data = ConversationMixin._extract_citation_data(
        [
            None,
            None,
            None,
            [
                _passage(["shared-id"], "source-1"),
                _passage(["shared-id"], "source-1"),
                _passage(["  "], "source-2"),
                _passage([" shared-id "], "source-2"),
                _passage([None], "source-2"),
            ],
        ]
    )
    assert data["sources_used"] == ["source-1", "source-2"]
    assert data["citations"] == {
        1: "source-1",
        2: "source-1",
        3: "source-2",
        4: "source-2",
        5: "source-2",
    }
    assert [ref["citation_number"] for ref in data["references"]] == [1, 2, 3, 4, 5]
    assert [ref.get("chunk_id") for ref in data["references"]] == [
        "shared-id",
        "shared-id",
        None,
        "shared-id",
        None,
    ]


def test_chunk_id_preserved_by_service_cli_and_mcp():
    data = ConversationMixin._extract_citation_data(
        [None, None, None, [_passage(["chunk-a"], "source-1")]]
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.query.return_value = {"answer": "Example answer", **data}
    aliases = MagicMock()
    aliases.resolve.side_effect = lambda value: value

    with (
        patch("notebooklm_tools.cli.commands.notebook.get_alias_manager", return_value=aliases),
        patch("notebooklm_tools.cli.commands.notebook.get_client", return_value=client),
        patch("notebooklm_tools.mcp.tools.chat.get_client", return_value=client),
    ):
        direct = query(client, "nb", "question", source_ids=["source-1"])
        cli = CliRunner().invoke(
            app, ["query", "nb", "question", "--source-ids", "source-1", "--json"]
        )
        mcp = asyncio.run(notebook_query("nb", "question", source_ids=["source-1"]))

    assert cli.exit_code == 0, cli.output
    assert mcp["status"] == "success"
    assert direct["references"] == json.loads(cli.output)["references"] == mcp["references"]
    assert mcp["references"][0]["chunk_id"] == "chunk-a"
