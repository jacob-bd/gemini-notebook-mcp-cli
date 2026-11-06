"""Regression coverage for unreadable source responses and notes-only notebooks."""

from unittest.mock import Mock

import pytest

from notebooklm_tools.core.client import NotebookLMClient
from notebooklm_tools.core.errors import RPCError
from notebooklm_tools.services.errors import ServiceError
from notebooklm_tools.services.studio import _resolve_source_ids


@pytest.mark.parametrize(
    "payload",
    [None, [], [[]], [["Title", {}, "nb"]], [["Title", [["bare-id", "Title", []]], "nb"]]],
)
def test_unreadable_sources_raise_instead_of_reporting_empty(payload):
    client = object.__new__(NotebookLMClient)
    client.get_notebook = Mock(return_value=payload)
    with pytest.raises(RPCError, match="Could not read notebook sources"):
        client.get_notebook_sources_with_types("nb")
    with pytest.raises(ServiceError, match="Failed to fetch sources"):
        _resolve_source_ids(client, "nb", None)


@pytest.mark.parametrize("sources", [None, [], [[["source-id"], "Source", []]]])
def test_notes_are_never_used_as_sources(sources):
    data = ["Title", sources, "nb"] + [None] * 14
    data.append([["note-id", None, [1, None, [0]], None, "Note"]])
    client = object.__new__(NotebookLMClient)
    client.get_notebook = Mock(return_value=[data])
    expected = ["source-id"] if sources else []
    assert client._get_all_source_ids("nb") == expected


def test_studio_preserves_source_lookup_failure_without_generation():
    client = object.__new__(NotebookLMClient)
    client.get_notebook = Mock(side_effect=TimeoutError("source lookup timed out"))
    client._call_rpc = Mock()
    with pytest.raises(TimeoutError, match="source lookup timed out"):
        client.create_quiz("nb")
    client._call_rpc.assert_not_called()
