"""Tests for CollectionsMixin.edit_collection payloads (le8sX)."""

from unittest.mock import patch

import pytest

from notebooklm_tools.core.collections import CollectionsMixin

COL_ID = "col-1"
CURRENT = ["nb-a", "nb-b"]


def _mixin():
    return CollectionsMixin(cookies={"test": "cookie"}, csrf_token="test")


def _edit_payloads(mock_rpc):
    """Return the 4th param (edit payload) of every le8sX call, in order."""
    return [c.args[1][3] for c in mock_rpc.call_args_list if c.args[0] == "le8sX"]


@pytest.fixture
def rpc():
    with patch.object(CollectionsMixin, "_refresh_auth_tokens"):  # noqa: SIM117
        with patch.object(CollectionsMixin, "_call_rpc", return_value=[]) as mock_rpc:
            with patch.object(
                CollectionsMixin,
                "list_collections",
                return_value=[
                    {"id": COL_ID, "name": "Group", "notebook_ids": CURRENT, "emoji": ""}
                ],
            ):
                yield mock_rpc


def test_rename_only_sends_name_operation(rpc):
    assert _mixin().edit_collection(COL_ID, name="New name") is True
    assert _edit_payloads(rpc) == [[[["New name"]]]]


def test_add_sends_only_new_ids(rpc):
    _mixin().edit_collection(COL_ID, notebook_ids=["nb-a", "nb-b", "nb-c", "nb-d"])
    assert _edit_payloads(rpc) == [[[None, None, None, [["nb-c", "nb-d"]]], []]]


def test_remove_sends_only_dropped_ids(rpc):
    _mixin().edit_collection(COL_ID, notebook_ids=["nb-b"])
    assert _edit_payloads(rpc) == [[[None, None, None, None, [["nb-a"]]], []]]


def test_add_remove_and_rename_are_separate_calls(rpc):
    _mixin().edit_collection(COL_ID, name="Group 2", notebook_ids=["nb-b", "nb-c"])
    assert _edit_payloads(rpc) == [
        [[["Group 2"]]],
        [[None, None, None, [["nb-c"]]], []],
        [[None, None, None, None, [["nb-a"]]], []],
    ]


def test_unchanged_list_sends_nothing(rpc):
    assert _mixin().edit_collection(COL_ID, notebook_ids=list(CURRENT)) is True
    assert _edit_payloads(rpc) == []


def test_params_shape(rpc):
    _mixin().edit_collection(COL_ID, name="X")
    params = rpc.call_args.args[1]
    assert params[1] is None
    assert params[2] == COL_ID
    assert params[4] == 3


def test_unknown_collection_raises(rpc):
    with pytest.raises(ValueError):
        _mixin().edit_collection("missing", notebook_ids=["nb-a"])


def test_unknown_collection_sends_no_rename(rpc):
    with pytest.raises(ValueError):
        _mixin().edit_collection("missing", name="New name", notebook_ids=["nb-a"])
    assert _edit_payloads(rpc) == []


def test_partial_failure_returns_false(rpc):
    rpc.side_effect = [[], None, []]
    assert _mixin().edit_collection(COL_ID, name="Group 2", notebook_ids=["nb-b", "nb-c"]) is False
    assert len(_edit_payloads(rpc)) == 3
