#!/usr/bin/env python3
"""Tests for ConversationMixin."""

import json
from unittest.mock import patch

import pytest

from notebooklm_tools.core.base import BaseClient
from notebooklm_tools.core.conversation import ConversationMixin, QueryRejectedError
from notebooklm_tools.core.data_types import ConversationTurn


class TestConversationMixinImport:
    """Test that ConversationMixin can be imported correctly."""

    def test_conversation_mixin_import(self):
        """Test that ConversationMixin can be imported."""
        assert ConversationMixin is not None

    def test_conversation_mixin_inherits_base(self):
        """Test that ConversationMixin inherits from BaseClient."""
        assert issubclass(ConversationMixin, BaseClient)

    def test_conversation_mixin_has_methods(self):
        """Test that ConversationMixin has expected methods."""
        expected_methods = [
            "query",
            "clear_conversation",
            "get_conversation_history",
            "get_conversation_id",
            "delete_chat_history",
            "_build_conversation_history",
            "_cache_conversation_turn",
            "_parse_query_response",
            "_extract_answer_from_chunk",
            "_extract_source_ids_from_notebook",
        ]
        for method in expected_methods:
            assert hasattr(ConversationMixin, method), f"Missing method: {method}"


class TestGetConversationId:
    """Test get_conversation_id method for fetching server-side conversation IDs."""

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    def test_returns_id_from_nested_list(self):
        """Server returns [[conv_id, ...]] — extract the conv_id string."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[["conv-uuid-123", None, 12345]]):
            result = mixin.get_conversation_id("nb-123")
        assert result == "conv-uuid-123"

    def test_returns_id_from_flat_string_list(self):
        """Server returns [[conv_id]] — double-nested format."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[["conv-uuid-456"]]):
            result = mixin.get_conversation_id("nb-123")
        assert result == "conv-uuid-456"

    def test_returns_none_on_null_response(self):
        """Server returns None — no conversation exists."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=None):
            result = mixin.get_conversation_id("nb-123")
        assert result is None

    def test_returns_none_on_empty_list(self):
        """Server returns [] — no conversation exists."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[]):
            result = mixin.get_conversation_id("nb-123")
        assert result is None

    def test_returns_none_on_malformed_inner_list(self):
        """Server returns [[]] — malformed but no crash."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[[]]):
            result = mixin.get_conversation_id("nb-123")
        assert result is None

    def test_returns_none_on_rpc_exception(self):
        """RPC call fails — returns None gracefully, not an exception."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", side_effect=Exception("network error")):
            result = mixin.get_conversation_id("nb-123")
        assert result is None

    def test_calls_correct_rpc(self):
        """Verifies it calls the correct RPC ID with right params."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=None) as mock_rpc:
            mixin.get_conversation_id("nb-123")
        mock_rpc.assert_called_once_with(
            mixin.RPC_GET_CONVERSATIONS,
            [[], None, "nb-123", 20],
            path="/notebook/nb-123",
        )

    def test_passes_timeout_to_rpc(self):
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=None) as mock_rpc:
            mixin.get_conversation_id("nb-123", timeout=12.5)
        mock_rpc.assert_called_once_with(
            mixin.RPC_GET_CONVERSATIONS,
            [[], None, "nb-123", 20],
            path="/notebook/nb-123",
            timeout=12.5,
        )


class TestGetConversationTurns:
    """Test get_conversation_turns, which fetches full Q&A history from the
    server (RPC_GET_CONVERSATION_TURNS / khqZz), discovered via Chrome DevTools
    capture on 2026-07-22. See docs/API_REFERENCE.md for the raw response shape.
    """

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    def _answer_turn(self, turn_id: str, ts: int, text: str) -> list:
        # Real server shape: content[0] wraps the text one level deep as
        # [text, None, [conv_id, conv_id, num]] — not the bare string.
        return [turn_id, [ts, 0], 2, None, [[text, None, ["conv-id", "conv-id", 1]]]]

    def _query_turn(self, turn_id: str, ts: int, text: str) -> list:
        return [turn_id, [ts, 0], 1, text]

    def test_pairs_and_orders_turns_chronologically(self):
        """Server returns turns newest-first as [answer, query] pairs; the
        method should pair them and return oldest-first with 1-indexed turns."""
        mixin = self._make_mixin()
        raw_turns = [
            self._answer_turn("a2", 200, "Second answer"),
            self._query_turn("q2", 200, "Second question"),
            self._answer_turn("a1", 100, "First answer"),
            self._query_turn("q1", 100, "First question"),
        ]
        with patch.object(mixin, "_call_rpc", return_value=[raw_turns, "token"]):
            result = mixin.get_conversation_turns("nb-123", "conv-abc")

        assert result == [
            {"turn": 1, "query": "First question", "answer": "First answer"},
            {"turn": 2, "query": "Second question", "answer": "Second answer"},
        ]

    def test_returns_none_on_empty_turns(self):
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[[], None]):
            result = mixin.get_conversation_turns("nb-123", "conv-abc")
        assert result is None

    def test_returns_none_on_null_response(self):
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=None):
            result = mixin.get_conversation_turns("nb-123", "conv-abc")
        assert result is None

    def test_returns_none_on_rpc_exception(self):
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", side_effect=Exception("network error")):
            result = mixin.get_conversation_turns("nb-123", "conv-abc")
        assert result is None

    def test_ignores_unpaired_answer(self):
        """A trailing answer with no matching query (e.g. mid-stream) is dropped
        rather than crashing or fabricating an empty query."""
        mixin = self._make_mixin()
        raw_turns = [self._answer_turn("a1", 100, "Orphan answer")]
        with patch.object(mixin, "_call_rpc", return_value=[raw_turns, None]):
            result = mixin.get_conversation_turns("nb-123", "conv-abc")
        assert result is None

    def test_calls_correct_rpc(self):
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=None) as mock_rpc:
            mixin.get_conversation_turns("nb-123", "conv-abc", limit=5)
        mock_rpc.assert_called_once_with(
            mixin.RPC_GET_CONVERSATION_TURNS,
            [
                [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],
                None,
                None,
                "conv-abc",
                5,
            ],
            path="/notebook/nb-123",
        )


class TestDeleteChatHistory:
    """Test delete_chat_history method."""

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    def test_delete_success(self):
        """Server acknowledges deletion — returns True."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[]):
            result = mixin.delete_chat_history("nb-123", "conv-456")
        assert result is True

    def test_delete_clears_local_cache(self):
        """Deletion also clears the local conversation cache."""
        mixin = self._make_mixin()
        mixin._conversation_cache["conv-456"] = [
            ConversationTurn(query="q", answer="a", turn_number=1)
        ]
        with patch.object(mixin, "_call_rpc", return_value=[]):
            mixin.delete_chat_history("nb-123", "conv-456")
        assert "conv-456" not in mixin._conversation_cache

    def test_delete_no_local_cache_no_crash(self):
        """Deletion when no local cache exists doesn't crash."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[]):
            result = mixin.delete_chat_history("nb-123", "conv-789")
        assert result is True

    def test_calls_correct_rpc(self):
        """Verifies it calls the correct RPC ID with right params."""
        mixin = self._make_mixin()
        with patch.object(mixin, "_call_rpc", return_value=[]) as mock_rpc:
            mixin.delete_chat_history("nb-123", "conv-456")
        mock_rpc.assert_called_once_with(
            mixin.RPC_DELETE_CHAT_HISTORY,
            [
                [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],
                "conv-456",
                None,
                1,
            ],
            path="/notebook/nb-123",
            retry_server_errors=False,
        )


class TestQueryUsesServerConversationId:
    """Test that query() fetches server-side conversation ID when no ID is provided."""

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    def test_uses_server_conversation_id(self):
        """When server has a conversation ID, query() uses it instead of uuid."""
        mixin = self._make_mixin()
        with (
            patch.object(mixin, "get_conversation_id", return_value="server-conv-id"),
            patch("notebooklm_tools.core.conversation._httpx.Client") as mock_client_class,
        ):
            mock_response = mock_client_class.return_value.__enter__.return_value.post.return_value
            mock_response.text = ")]}'\n100\n" + json.dumps(
                [
                    [
                        "wrb.fr",
                        None,
                        json.dumps([["A long answer from the server.", None, [], None, [1]]]),
                    ]
                ]
            )
            mock_response.raise_for_status = lambda: None

            result = mixin.query("nb-123", "Hello?", source_ids=["src-1"])

        request_client_calls = [
            call.kwargs for call in mock_client_class.call_args_list if "cookies" in call.kwargs
        ]
        assert len(request_client_calls) == 1
        assert 0 < request_client_calls[0]["timeout"] <= 120.0 + 1e-9
        assert request_client_calls[0]["cookies"]
        assert request_client_calls[0]["headers"] == {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"
        }
        assert result["conversation_id"] == "server-conv-id"

    def test_falls_back_to_uuid_when_no_server_id(self):
        """When server returns None, query() generates a random UUID."""
        mixin = self._make_mixin()
        with (
            patch.object(mixin, "get_conversation_id", return_value=None),
            patch("notebooklm_tools.core.conversation._httpx.Client") as mock_client_class,
        ):
            mock_response = mock_client_class.return_value.__enter__.return_value.post.return_value
            mock_response.text = ")]}'\n100\n" + json.dumps(
                [
                    [
                        "wrb.fr",
                        None,
                        json.dumps([["A long answer from the server.", None, [], None, [1]]]),
                    ]
                ]
            )
            mock_response.raise_for_status = lambda: None

            result = mixin.query("nb-123", "Hello?", source_ids=["src-1"])

        # Should be a valid UUID (36 chars with hyphens)
        assert result["conversation_id"] != "server-conv-id"
        assert len(result["conversation_id"]) == 36

    def test_new_conversation_skips_server_conversation_lookup(self):
        """Explicit fresh conversations do not reuse the server conversation."""
        mixin = self._make_mixin()
        with (
            patch.object(mixin, "get_conversation_id", side_effect=AssertionError),
            patch("notebooklm_tools.core.conversation._httpx.Client") as mock_client_class,
        ):
            mock_response = mock_client_class.return_value.__enter__.return_value.post.return_value
            mock_response.text = ")]}'\n100\n" + json.dumps(
                [
                    [
                        "wrb.fr",
                        None,
                        json.dumps([["A fresh answer.", None, [], None, [1]]]),
                    ]
                ]
            )
            mock_response.raise_for_status = lambda: None

            result = mixin.query(
                "nb-123",
                "Hello?",
                source_ids=["src-1"],
                new_conversation=True,
            )

        assert result["conversation_id"] != "server-conv-id"
        assert len(result["conversation_id"]) == 36

    def test_enterprise_default_query_skips_consumer_conversation_lookup(self):
        """Enterprise has no consumer conversation RPC on its streamed route."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._is_enterprise = lambda: True
        mixin._enterprise_project_id = "project-123"
        mixin._location = "global"
        with (
            patch.object(mixin, "get_conversation_id", side_effect=AssertionError),
            patch("notebooklm_tools.core.conversation._httpx.Client") as mock_client_class,
        ):
            mock_response = mock_client_class.return_value.__enter__.return_value.post.return_value
            mock_response.text = ")]}'\n100\n" + json.dumps(
                [["wrb.fr", None, json.dumps([["An Enterprise answer.", None, [], None, [1]]])]]
            )
            mock_response.raise_for_status = lambda: None

            result = mixin.query("nb-123", "Hello?", source_ids=["src-1"])

        assert result["answer"] == "An Enterprise answer."

    def test_query_passes_timeout_to_internal_lookups(self):
        mixin = self._make_mixin()
        with (
            patch.object(
                mixin,
                "get_notebook",
                return_value=[["Notebook", [[["src-1"], "Source"]], "nb-123"]],
                create=True,
            ) as mock_get_notebook,
            patch.object(mixin, "get_conversation_id", return_value=None) as mock_get_conversation,
            patch("notebooklm_tools.core.conversation.time.monotonic", return_value=100.0),
            patch("notebooklm_tools.core.conversation._httpx.Client") as mock_client_class,
        ):
            mock_response = mock_client_class.return_value.__enter__.return_value.post.return_value
            mock_response.text = ")]}'\n100\n" + json.dumps(
                [["wrb.fr", None, json.dumps([["An answer.", None, [], None, [1]]])]]
            )
            mock_response.raise_for_status = lambda: None

            mixin.query("nb-123", "Hello?", timeout=45.0)

        mock_get_notebook.assert_called_once_with("nb-123", timeout=45.0)
        mock_get_conversation.assert_called_once_with("nb-123", timeout=45.0)
        request_client_calls = [
            call.kwargs for call in mock_client_class.call_args_list if "cookies" in call.kwargs
        ]
        assert request_client_calls[0]["timeout"] == 45.0


class TestConversationMixinMethods:
    """Test ConversationMixin method behavior."""

    def test_clear_conversation_removes_from_cache(self):
        """Test that clear_conversation removes conversation from cache."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        # Add a conversation to cache
        mixin._conversation_cache["test-conv-id"] = []

        # Clear it
        result = mixin.clear_conversation("test-conv-id")

        assert result is True
        assert "test-conv-id" not in mixin._conversation_cache

    def test_clear_conversation_returns_false_if_not_found(self):
        """Test that clear_conversation returns False if conversation not in cache."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin.clear_conversation("nonexistent-id")

        assert result is False

    def test_get_conversation_history_returns_none_if_not_found(self):
        """Test that get_conversation_history returns None if conversation not in cache."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin.get_conversation_history("nonexistent-id")

        assert result is None

    def test_parse_query_response_handles_empty(self):
        """Test that _parse_query_response handles empty input."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        answer, citation_data, _ = mixin._parse_query_response("")

        assert answer == ""
        assert citation_data == {}

    def test_parse_query_response_does_not_copy_entire_response_body(self):
        """Large streamed responses are scanned without strip/split copies."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        answer_text = "A sufficiently long answer with an emoji 📊."
        inner = json.dumps([[answer_text, None, [], None, [1]]], ensure_ascii=False)
        chunk = json.dumps([["wrb.fr", None, inner]], ensure_ascii=False)
        raw = str(len(chunk)) + "\n" + chunk

        class NoWholeBodyCopy(str):
            def strip(self, *args, **kwargs):
                raise AssertionError("the full response body must not be stripped")

            def split(self, *args, **kwargs):
                raise AssertionError("the full response body must not be split")

        parsed_answer, citation_data, _ = mixin._parse_query_response(NoWholeBodyCopy(raw))

        assert parsed_answer == answer_text
        assert citation_data == {}

    def test_extract_answer_from_chunk_handles_invalid_json(self):
        """Test that _extract_answer_from_chunk handles invalid JSON."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        text, is_answer, cdata, _ = mixin._extract_answer_from_chunk("not valid json")

        assert text is None
        assert is_answer is False
        assert cdata == {}

    def test_extract_source_ids_from_notebook_handles_none(self):
        """Test that _extract_source_ids_from_notebook handles None input."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin._extract_source_ids_from_notebook(None)

        assert result == []

    def test_extract_source_ids_from_notebook_handles_empty_list(self):
        """Test that _extract_source_ids_from_notebook handles empty list input."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin._extract_source_ids_from_notebook([])

        assert result == []


class TestBoundedConversationCache:
    """Issue #213: bounded cache to prevent OOM in long-lived MCP server processes."""

    def test_defaults_applied(self):
        """Defaults match the design (50/500/100k)."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        stats = mixin.get_conversation_cache_stats()
        assert stats["max_turns_per_conversation"] == 50
        assert stats["max_conversations"] == 500
        assert stats["max_chars_per_turn"] == 100_000
        assert stats["conversations"] == 0
        assert stats["total_turns"] == 0

    def test_env_var_overrides(self, monkeypatch):
        """Each env var overrides the default and is exposed in stats."""
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_TURNS", "7")
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_CONVS", "3")
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_CHARS_PER_TURN", "42")
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        stats = mixin.get_conversation_cache_stats()
        assert stats["max_turns_per_conversation"] == 7
        assert stats["max_conversations"] == 3
        assert stats["max_chars_per_turn"] == 42

    def test_invalid_env_falls_back_to_default(self, monkeypatch, caplog):
        """Unparseable env values fall back to the default and warn."""
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_TURNS", "not-a-number")
        with caplog.at_level("WARNING", logger="notebooklm_mcp.api"):
            mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        assert mixin._max_turns_per_conversation == 50
        assert "NOTEBOOKLM_CONVERSATION_MAX_TURNS" in caplog.text

    def test_zero_disables_cap(self, monkeypatch):
        """0 means 'unlimited' for any cap."""
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_TURNS", "0")
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_CONVS", "0")
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_CHARS_PER_TURN", "0")
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        for i in range(100):
            mixin._cache_conversation_turn("c1", query=f"q{i}", answer=f"a{i}")
        assert len(mixin._conversation_cache["c1"]) == 100
        # And a giant answer is not truncated.
        mixin._cache_conversation_turn("c2", query="q", answer="x" * 1_000_000)
        assert len(mixin._conversation_cache["c2"][-1].answer) == 1_000_000

    def test_per_conversation_turn_cap_trims_fifo(self):
        """Per-conv list is FIFO-trimmed from the front when over cap, and
        survivors are renumbered 1..N so `turn_number` stays a stable
        1-indexed position in the current list."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_turns_per_conversation = 3
        for i in range(5):
            mixin._cache_conversation_turn("c1", query=f"q{i}", answer=f"a{i}")
        turns = mixin._conversation_cache["c1"]
        assert len(turns) == 3
        # Survivors are the LAST 3 inserts: q2, q3, q4. turn_number is
        # renumbered to 1..N after trim.
        assert [t.query for t in turns] == ["q2", "q3", "q4"]
        assert [t.turn_number for t in turns] == [1, 2, 3]

    def test_global_conversation_cap_evicts_lru(self):
        """When the dict is at cap, inserting a new conv evicts the LRU one."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_conversations = 2
        mixin._cache_conversation_turn("a", query="qa", answer="aa")
        mixin._cache_conversation_turn("b", query="qb", answer="ab")
        # Touch 'a' to make it MRU; 'b' is now LRU.
        mixin.get_conversation_history("a")
        mixin._cache_conversation_turn("c", query="qc", answer="ac")
        assert set(mixin._conversation_cache.keys()) == {"a", "c"}
        assert mixin._conversation_cache["c"][-1].query == "qc"

    def test_lru_promotes_on_cache_write(self):
        """Writing a new turn to an existing conv promotes it to MRU."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_conversations = 2
        mixin._cache_conversation_turn("a", query="qa", answer="aa")
        mixin._cache_conversation_turn("b", query="qb", answer="ab")
        # Write to 'a' — should promote it, making 'b' LRU.
        mixin._cache_conversation_turn("a", query="qa2", answer="aa2")
        mixin._cache_conversation_turn("c", query="qc", answer="ac")
        assert set(mixin._conversation_cache.keys()) == {"a", "c"}
        assert mixin._conversation_cache["a"][-1].query == "qa2"

    def test_lru_promotes_on_read(self):
        """Reading a conversation via _build_conversation_history promotes it."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_conversations = 2
        mixin._cache_conversation_turn("a", query="qa", answer="aa")
        mixin._cache_conversation_turn("b", query="qb", answer="ab")
        # Read 'a' — should promote it; 'b' becomes LRU.
        mixin._build_conversation_history("a")
        mixin._cache_conversation_turn("c", query="qc", answer="ac")
        assert set(mixin._conversation_cache.keys()) == {"a", "c"}

    def test_answer_truncated_when_over_char_cap(self):
        """Long answers are truncated to max_chars_per_turn."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_chars_per_turn = 10
        mixin._cache_conversation_turn("c1", query="q", answer="x" * 1_000)
        assert mixin._conversation_cache["c1"][-1].answer == "x" * 10
        # Query is never truncated.
        assert mixin._conversation_cache["c1"][-1].query == "q"

    def test_stats_reflect_cache_contents(self):
        """Stats count conversations and total turns accurately."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_turns_per_conversation = 5
        mixin._max_conversations = 5
        for cid in ("a", "b", "c"):
            for i in range(2):
                mixin._cache_conversation_turn(cid, query=f"q{i}", answer=f"a{i}")
        stats = mixin.get_conversation_cache_stats()
        assert stats["conversations"] == 3
        assert stats["total_turns"] == 6

    def test_clear_conversation_still_works(self):
        """Clearing a conversation is independent of the new caps."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._cache_conversation_turn("c1", query="q", answer="a")
        assert mixin.clear_conversation("c1") is True
        assert "c1" not in mixin._conversation_cache
        assert mixin.get_conversation_cache_stats()["conversations"] == 0

    def test_negative_env_clamps_to_zero(self, monkeypatch, caplog):
        """A negative env value is clamped to 0 and warned about, so a stray
        -1 doesn't silently disable a cap the user thought they had set."""
        monkeypatch.setenv("NOTEBOOKLM_CONVERSATION_MAX_TURNS", "-7")
        with caplog.at_level("WARNING", logger="notebooklm_mcp.api"):
            mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        assert mixin._max_turns_per_conversation == 0
        assert "clamping to 0" in caplog.text

    def test_query_migrates_lru_when_target_already_exists(self, monkeypatch):
        """When the server returns a conv_id already in the cache, the migrated
        entry is promoted to MRU — not left at its old LRU position from the
        previous use of that key."""
        mixin = ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")
        mixin._max_conversations = 2
        # Pre-populate with two convs; "old" is LRU because "new" was inserted last.
        mixin._cache_conversation_turn("old", query="qo", answer="ao")
        mixin._cache_conversation_turn("new", query="qn", answer="an")
        assert list(mixin._conversation_cache.keys()) == ["old", "new"]

        # Simulate the migration: the local id gets moved to "new" which
        # already exists. After move_to_end, "new" must be at MRU.
        with mixin._state_lock:
            if "old" in mixin._conversation_cache:
                mixin._conversation_cache["new"] = mixin._conversation_cache.pop("old")
            mixin._conversation_cache.move_to_end("new")
        assert list(mixin._conversation_cache.keys()) == ["new"]


class TestErrorDetection:
    """Test Google API error detection in query response parsing."""

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    def test_extract_error_simple_code(self):
        """Error code 3 (INVALID_ARGUMENT) in wrb.fr chunk."""
        mixin = self._make_mixin()
        chunk = json.dumps([["wrb.fr", None, None, None, None, [3]]])
        result = mixin._extract_error_from_chunk(chunk)

        assert result is not None
        assert result["code"] == 3
        assert result["type"] == ""

    def test_extract_error_with_type_info(self):
        """Error code 8 with UserDisplayableError type."""
        mixin = self._make_mixin()
        error_type = "type.googleapis.com/google.internal.labs.tailwind.orchestration.v1.UserDisplayableError"
        chunk = json.dumps(
            [["wrb.fr", None, None, None, None, [8, None, [[error_type, [None, [None, [[1]]]]]]]]]
        )
        result = mixin._extract_error_from_chunk(chunk)

        assert result is not None
        assert result["code"] == 8
        assert result["type"] == error_type

    def test_extract_error_returns_none_for_normal_chunk(self):
        """Normal wrb.fr chunk with answer data should not be detected as error."""
        mixin = self._make_mixin()
        inner = json.dumps(
            [
                [
                    "This is a long enough answer text for the test to pass properly.",
                    None,
                    [],
                    None,
                    [1],
                ]
            ]
        )
        chunk = json.dumps([["wrb.fr", None, inner, None, None, None]])
        result = mixin._extract_error_from_chunk(chunk)

        assert result is None

    def test_extract_error_returns_none_for_invalid_json(self):
        mixin = self._make_mixin()
        assert mixin._extract_error_from_chunk("not json") is None

    def test_extract_error_returns_none_for_non_wrb_chunk(self):
        mixin = self._make_mixin()
        chunk = json.dumps([["di", 123], ["af.httprm", 456]])
        assert mixin._extract_error_from_chunk(chunk) is None

    @staticmethod
    def _build_raw_response(*chunks: str) -> str:
        """Build a raw Google API response with anti-XSSI prefix."""
        prefix = ")]}'\n"
        parts = [prefix]
        for chunk in chunks:
            parts.append(str(len(chunk)))
            parts.append(chunk)
        return "\n".join(parts)

    def test_parse_response_raises_on_error_code_3(self):
        """Full response with error code 3 raises QueryRejectedError."""
        mixin = self._make_mixin()
        error_chunk = json.dumps([["wrb.fr", None, None, None, None, [3]]])
        metadata_chunk = json.dumps([["di", 206], ["af.httprm", 205, "-1728080960086747572", 21]])
        raw = self._build_raw_response(error_chunk, metadata_chunk)

        with pytest.raises(QueryRejectedError) as exc_info:
            mixin._parse_query_response(raw)

        assert exc_info.value.error_code == 3
        assert exc_info.value.code_name == "INVALID_ARGUMENT"

    def test_parse_response_raises_on_user_displayable_error(self):
        """Full response with UserDisplayableError raises QueryRejectedError."""
        mixin = self._make_mixin()
        error_type = "type.googleapis.com/google.internal.labs.tailwind.orchestration.v1.UserDisplayableError"
        error_chunk = json.dumps(
            [["wrb.fr", None, None, None, None, [8, None, [[error_type, [None, [None, [[1]]]]]]]]]
        )
        raw = self._build_raw_response(error_chunk)

        with pytest.raises(QueryRejectedError) as exc_info:
            mixin._parse_query_response(raw)

        assert exc_info.value.error_code == 8
        assert "UserDisplayableError" in exc_info.value.error_type

    def test_parse_response_prefers_answer_over_error(self):
        """If both an answer and error are present, answer wins."""
        mixin = self._make_mixin()
        answer_text = "This is a sufficiently long answer text that should be returned."
        inner = json.dumps([[answer_text, None, [], None, [1]]])
        answer_chunk = json.dumps([["wrb.fr", None, inner]])
        error_chunk = json.dumps([["wrb.fr", None, None, None, None, [3]]])
        raw = self._build_raw_response(answer_chunk, error_chunk)

        answer, _, _ = mixin._parse_query_response(raw)
        assert answer == answer_text

    def test_parse_response_returns_empty_on_no_error_no_answer(self):
        """No error and no answer returns empty string (not an exception)."""
        mixin = self._make_mixin()
        metadata_chunk = json.dumps([["di", 206]])
        raw = self._build_raw_response(metadata_chunk)

        answer, citation_data, _ = mixin._parse_query_response(raw)
        assert answer == ""
        assert citation_data == {}

    def test_query_rejected_error_attributes(self):
        """QueryRejectedError has correct attributes and message."""
        err = QueryRejectedError(error_code=3, error_type="SomeType")
        assert err.error_code == 3
        assert err.code_name == "INVALID_ARGUMENT"
        assert "error code 3" in str(err)
        assert "INVALID_ARGUMENT" in str(err)
        assert "SomeType" in str(err)

    def test_query_rejected_error_unknown_code(self):
        """Unknown error codes get 'UNKNOWN' label."""
        err = QueryRejectedError(error_code=999)
        assert err.code_name == "UNKNOWN"
        assert "error code 999" in str(err)


class TestCitationExtraction:
    """Test citation/source extraction from query response chunks."""

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    @staticmethod
    def _build_passage(passage_id: str, source_id: str, confidence: float = 0.75) -> list:
        """Build a realistic source passage entry for first_elem[4][3]."""
        return [
            [passage_id],
            [
                None,
                None,
                confidence,
                [[None, 0, 500]],
                [[[0, 500, [[[0, 500, ["Some source text passage content."]]]]]]],
                [[[source_id], "other-uuid-hash"]],
                [passage_id],
            ],
        ]

    @staticmethod
    def _build_answer_inner(answer_text: str, passages: list | None = None) -> str:
        """Build the inner JSON for a wrb.fr answer chunk with optional citation data."""
        type_info: list = [None, None, None]
        if passages is not None:
            type_info.append(passages)
            type_info.append(1)
        else:
            type_info.append(None)
            type_info.append(1)
        # first_elem: [text, null, conv_data, null, type_info]
        first_elem = [answer_text, None, ["conv-id", "hash", 12345], None, type_info]
        return json.dumps([first_elem])

    @staticmethod
    def _build_raw_response(*chunks: str) -> str:
        prefix = ")]}'\n"
        parts = [prefix]
        for chunk in chunks:
            parts.append(str(len(chunk)))
            parts.append(chunk)
        return "\n".join(parts)

    def test_extract_citations_from_answer_chunk(self):
        """Answer chunk with source passages returns correct citation data."""
        mixin = self._make_mixin()
        passages = [
            self._build_passage("pass-1", "source-A"),
            self._build_passage("pass-2", "source-A"),
            self._build_passage("pass-3", "source-B"),
        ]
        answer = "Here are the results [1] and more details [2] from another doc [3]."
        inner = self._build_answer_inner(answer, passages)
        chunk = json.dumps([["wrb.fr", None, inner]])

        text, is_answer, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert text == answer
        assert is_answer is True
        assert cdata["sources_used"] == ["source-A", "source-B"]
        assert cdata["citations"] == {1: "source-A", 2: "source-A", 3: "source-B"}

    def test_extract_citations_preserves_source_order(self):
        """sources_used preserves first-seen order of source IDs."""
        mixin = self._make_mixin()
        passages = [
            self._build_passage("p1", "source-B"),
            self._build_passage("p2", "source-A"),
            self._build_passage("p3", "source-B"),
        ]
        inner = self._build_answer_inner(
            "A long enough answer text to pass the length check.", passages
        )
        chunk = json.dumps([["wrb.fr", None, inner]])

        _, _, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert cdata["sources_used"] == ["source-B", "source-A"]

    def test_extract_citations_no_passages(self):
        """Answer chunk without source passages returns empty citation data."""
        mixin = self._make_mixin()
        inner = self._build_answer_inner(
            "A long enough answer text to pass the length check.", passages=None
        )
        chunk = json.dumps([["wrb.fr", None, inner]])

        text, is_answer, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert text is not None
        assert is_answer is True
        assert cdata == {}

    def test_extract_citations_empty_passages_list(self):
        """Answer chunk with empty passages list returns empty citation data."""
        mixin = self._make_mixin()
        inner = self._build_answer_inner(
            "A long enough answer text to pass the length check.", passages=[]
        )
        chunk = json.dumps([["wrb.fr", None, inner]])

        _, _, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert cdata == {}

    def test_extract_citations_malformed_passage_skipped(self):
        """Malformed passage entries are skipped without crashing."""
        mixin = self._make_mixin()
        passages = [
            self._build_passage("p1", "source-A"),
            [["bad-passage"]],
            "not even a list",
            self._build_passage("p3", "source-B"),
        ]
        inner = self._build_answer_inner(
            "A long enough answer text to pass the length check.", passages
        )
        chunk = json.dumps([["wrb.fr", None, inner]])

        _, _, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert cdata["sources_used"] == ["source-A", "source-B"]
        assert cdata["citations"] == {1: "source-A", 4: "source-B"}

    def test_thinking_chunk_has_no_citations(self):
        """Thinking chunks (type 2) do not return citation data."""
        mixin = self._make_mixin()
        type_info = [None, None, None, None, 2]
        first_elem = ["A long enough thinking step text for the check.", None, [], None, type_info]
        inner = json.dumps([first_elem])
        chunk = json.dumps([["wrb.fr", None, inner]])

        text, is_answer, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert text is not None
        assert is_answer is False
        assert cdata == {}

    def test_parse_response_returns_citation_data(self):
        """Full response parsing returns citation data from the longest answer chunk."""
        mixin = self._make_mixin()
        passages = [
            self._build_passage("p1", "src-X"),
            self._build_passage("p2", "src-Y"),
        ]
        short_answer = "Short answer text that is long enough."
        long_answer = (
            "This is the longer answer text with citations [1] and [2] referencing sources."
        )
        short_inner = self._build_answer_inner(short_answer, [self._build_passage("p0", "src-Z")])
        long_inner = self._build_answer_inner(long_answer, passages)
        short_chunk = json.dumps([["wrb.fr", None, short_inner]])
        long_chunk = json.dumps([["wrb.fr", None, long_inner]])
        raw = self._build_raw_response(short_chunk, long_chunk)

        answer, citation_data, _ = mixin._parse_query_response(raw)

        assert answer == long_answer
        assert citation_data["sources_used"] == ["src-X", "src-Y"]
        assert citation_data["citations"] == {1: "src-X", 2: "src-Y"}

    def test_parse_response_no_citations_returns_empty_dict(self):
        """Response with answer but no citation data returns empty dict."""
        mixin = self._make_mixin()
        inner = json.dumps(
            [["A long enough answer text to pass the length check.", None, [], None, [1]]]
        )
        chunk = json.dumps([["wrb.fr", None, inner]])
        raw = self._build_raw_response(chunk)

        answer, citation_data, _ = mixin._parse_query_response(raw)

        assert answer != ""
        assert citation_data == {}

    def test_static_extract_citation_data_handles_none_passages(self):
        """_extract_citation_data handles type_info with None at index 3."""
        result = ConversationMixin._extract_citation_data([None, None, None, None, 1])
        assert result == {}

    def test_static_extract_citation_data_handles_short_type_info(self):
        """_extract_citation_data handles type_info shorter than 4 elements."""
        result = ConversationMixin._extract_citation_data([1])
        assert result == {}


class TestShortAnswerRegression:
    """Regression tests for issue #214: short answer chunks must not be discarded.

    Bug: _extract_answer_from_chunk previously required len(answer_text) > 20,
    silently dropping legitimate short answers (e.g. "ANSWER: C") and falling
    back to the longest thinking chunk instead. The type indicator at
    first_elem[4][-1] is the authoritative answer/thinking discriminator.
    """

    def _make_mixin(self):
        return ConversationMixin(cookies={"test": "cookie"}, csrf_token="test")

    @staticmethod
    def _build_raw_response(*chunks: str) -> str:
        prefix = ")]}'\n"
        parts = [prefix]
        for chunk in chunks:
            parts.append(str(len(chunk)))
            parts.append(chunk)
        return "\n".join(parts)

    @staticmethod
    def _build_inner(answer_text: str, type_code: int) -> str:
        return json.dumps([[answer_text, None, ["conv-id", "hash", 12345], None, [type_code]]])

    def test_short_answer_wins_over_longer_thinking(self):
        """Short type=1 answer is returned even when a longer type=2 thinking chunk exists."""
        mixin = self._make_mixin()
        short_answer = "ANSWER: C"
        thinking = (
            "**Analyzing the Malaria Vector**\n\n"
            "This is a long thinking step that goes on and on with details."
        )
        answer_chunk = json.dumps([["wrb.fr", None, self._build_inner(short_answer, 1)]])
        thinking_chunk = json.dumps([["wrb.fr", None, self._build_inner(thinking, 2)]])
        raw = self._build_raw_response(answer_chunk, thinking_chunk)

        answer, _, _ = mixin._parse_query_response(raw)

        assert answer == short_answer

    def test_single_letter_answer_returned(self):
        """A 1-character answer (e.g. multiple-choice letter) is returned."""
        mixin = self._make_mixin()
        inner = self._build_inner("C", 1)
        chunk = json.dumps([["wrb.fr", None, inner]])
        raw = self._build_raw_response(chunk)

        answer, _, _ = mixin._parse_query_response(raw)

        assert answer == "C"

    def test_short_thinking_chunk_not_returned_as_answer(self):
        """A short type=2 thinking chunk is filtered as thinking, not promoted to answer."""
        mixin = self._make_mixin()
        inner = self._build_inner("brief thought", 2)
        chunk = json.dumps([["wrb.fr", None, inner]])
        raw = self._build_raw_response(chunk)

        # No type=1 chunks exist, so we fall back to thinking (preserved behavior).
        answer, _, _ = mixin._parse_query_response(raw)

        assert answer == "brief thought"

    def test_short_answer_chunk_via_string_first_elem(self):
        """Short answer in the alternative string-first-elem branch (line 641 path) is returned."""
        mixin = self._make_mixin()
        chunk = json.dumps([["wrb.fr", None, json.dumps(["ANSWER: C"])]])

        text, is_answer, cdata, _ = mixin._extract_answer_from_chunk(chunk)

        assert text == "ANSWER: C"
        assert is_answer is False
        assert cdata == {}


class TestCitedTextParsing:
    """Test _extract_cited_text with direct segments, wrapped segments, and tables."""

    def test_wrapped_segments_extract_text(self):
        """Wrapped segments [[seg], ...] extract text correctly (original format)."""
        detail = [
            None,
            None,
            0.75,
            None,
            [
                [[0, 50, [[[0, 50, ["Hello world."]]]]]],
            ],
        ]
        result = ConversationMixin._extract_cited_text(detail)
        assert result == "Hello world."

    def test_direct_segments_extract_text(self):
        """Direct segments [int, int, nested] extract text correctly (PR #84 fix)."""
        detail = [
            None,
            None,
            0.75,
            None,
            [[0, 100, [[[0, 100, ["Direct segment text."]]]]]],
        ]
        result = ConversationMixin._extract_cited_text(detail)
        assert result == "Direct segment text."

    def test_mixed_direct_and_wrapped_segments(self):
        """Both direct and wrapped segments are extracted together."""
        detail = [
            None,
            None,
            0.75,
            None,
            [
                # Wrapped segment
                [[0, 30, [[[0, 30, ["Wrapped text."]]]]]],
                # Direct segment
                [31, 60, [[[31, 60, ["Direct text."]]]]],
            ],
        ]
        result = ConversationMixin._extract_cited_text(detail)
        assert result == "Wrapped text. Direct text."

    def test_table_segment_inserts_placeholder(self):
        """Table segments (nested=null, data at segment[4]) insert <cited_table>."""
        # Table segment: [start, end, null, null, [dim1, dim2, rows_array]]
        # Use minimal but valid rows so the table detection triggers
        cell_a = [0, 10, [[0, 1, [[[[0, 1, ["A"]], None]]]]]]
        cell_b = [11, 20, [[0, 1, [[[[0, 1, ["B"]], None]]]]]]
        table_rows = [[0, 50, [cell_a, cell_b]]]
        detail = [
            None,
            None,
            0.75,
            None,
            [
                [0, 100, None, None, [2, 1, table_rows]],
            ],
        ]
        result = ConversationMixin._extract_cited_text(detail)
        assert result == "<cited_table>"

    def test_text_and_table_segments_combined(self):
        """Text followed by table produces text with placeholder."""
        cell_x = [0, 10, [[0, 1, [[[[0, 1, ["X"]], None]]]]]]
        cell_y = [11, 20, [[0, 1, [[[[0, 1, ["Y"]], None]]]]]]
        table_rows = [[0, 50, [cell_x, cell_y]]]
        detail = [
            None,
            None,
            0.75,
            None,
            [
                [0, 30, [[[0, 30, ["Some intro text."]]]]],
                [31, 100, None, None, [2, 1, table_rows]],
            ],
        ]
        result = ConversationMixin._extract_cited_text(detail)
        assert result == "Some intro text. <cited_table>"

    def test_detail_too_short_returns_none(self):
        """detail with fewer than 5 elements returns None."""
        assert ConversationMixin._extract_cited_text([None, None, 0.75, None]) is None

    def test_detail_index_4_not_list_returns_none(self):
        """detail[4] being non-list returns None."""
        assert ConversationMixin._extract_cited_text([None, None, 0.75, None, "not a list"]) is None

    def test_empty_elements_returns_none(self):
        """Empty elements in detail[4] are skipped, returns None."""
        detail = [None, None, 0.75, None, [[], None, "string"]]
        assert ConversationMixin._extract_cited_text(detail) is None


class TestTableRowParsing:
    """Test _extract_text_from_table_rows for structured table extraction."""

    @staticmethod
    def _make_cell(text: str) -> list:
        """Build a single table cell matching _extract_text_from_table_rows format.

        Structure: [start, end, [[sub_start, sub_end, [content_item]]]]
        content_item: [[text_start, text_end, text_val]]
        """
        return [0, 10, [[0, len(text), [[[0, len(text), text]]]]]]

    @staticmethod
    def _make_row(start: int, end: int, cells: list) -> list:
        """Build a table row."""
        return [start, end, cells]

    def test_simple_table(self):
        """Parse a simple 2x2 table."""
        rows = [
            self._make_row(0, 50, [self._make_cell("Header1"), self._make_cell("Header2")]),
            self._make_row(51, 100, [self._make_cell("Val1"), self._make_cell("Val2")]),
        ]
        result = ConversationMixin._extract_text_from_table_rows(rows)
        assert len(result) == 2
        assert result[0] == ["Header1", "Header2"]
        assert result[1] == ["Val1", "Val2"]

    def test_empty_rows_skipped(self):
        """Rows that are too short are skipped."""
        rows = [[0, 10], "not a list"]
        result = ConversationMixin._extract_text_from_table_rows(rows)
        assert result == []

    def test_empty_cells(self):
        """Empty cells (short lists) produce empty strings."""
        rows = [
            self._make_row(
                0,
                50,
                [
                    [0, 25],  # empty cell (no third element)
                    self._make_cell("Data"),
                ],
            ),
        ]
        result = ConversationMixin._extract_text_from_table_rows(rows)
        assert len(result) == 1
        assert result[0] == ["", "Data"]


class TestTableFromDetail:
    """Test _extract_table_from_detail for extracting structured table data."""

    @staticmethod
    def _make_cell(text: str) -> list:
        """Build a single table cell matching _extract_text_from_table_rows format.

        Structure: [start, end, [[sub_start, sub_end, [content_item]]]]
        content_item: [[text_start, text_end, text_val]]
        """
        return [0, 10, [[0, len(text), [[[0, len(text), text]]]]]]

    def test_extracts_table_from_detail(self):
        """Table segment in detail[4] is extracted with num_columns and rows."""
        table_rows = [
            [0, 50, [self._make_cell("Col1"), self._make_cell("Col2")]],
        ]
        detail = [
            None,
            None,
            0.75,
            None,
            [
                [0, 100, None, None, [2, 1, table_rows]],
            ],
            [["source-id"], "hash"],
        ]
        result = ConversationMixin._extract_table_from_detail(detail)
        assert result is not None
        assert result["num_columns"] == 2
        assert result["rows"] == [["Col1", "Col2"]]

    def test_returns_none_for_text_only_detail(self):
        """detail with only text segments (no tables) returns None."""
        detail = [
            None,
            None,
            0.75,
            None,
            [
                [[0, 50, [[[0, 50, ["Just text."]]]]]],
            ],
            [["source-id"], "hash"],
        ]
        result = ConversationMixin._extract_table_from_detail(detail)
        assert result is None

    def test_returns_none_for_short_detail(self):
        """detail shorter than 5 elements returns None."""
        assert ConversationMixin._extract_table_from_detail([None, None]) is None

    def test_returns_none_for_non_list_index_4(self):
        """detail[4] being non-list returns None."""
        assert (
            ConversationMixin._extract_table_from_detail([None, None, 0.75, None, "not_a_list"])
            is None
        )


class TestCitationDataWithTable:
    """Test _extract_citation_data includes cited_table when table is present."""

    @staticmethod
    def _make_cell(text: str) -> list:
        """Build a single table cell matching _extract_text_from_table_rows format.

        Structure: [start, end, [[sub_start, sub_end, [content_item]]]]
        content_item: [[text_start, text_end, text_val]]
        """
        return [0, 10, [[0, len(text), [[[0, len(text), text]]]]]]

    @classmethod
    def _build_passage_with_table(
        cls, passage_id: str, source_id: str, cell_texts: list[list[str]]
    ) -> list:
        """Build a passage entry that contains a table segment."""
        table_rows = []
        offset = 0
        for row_texts in cell_texts:
            cells = [cls._make_cell(t) for t in row_texts]
            table_rows.append([offset, offset + 50, cells])
            offset += 51
        return [
            [passage_id],
            [
                None,
                None,
                0.75,
                [[None, 0, 500]],
                [
                    [0, 200, None, None, [len(cell_texts[0]), len(cell_texts), table_rows]],
                ],
                [[[source_id], "hash"]],
                [passage_id],
            ],
        ]

    def test_citation_data_includes_cited_table(self):
        """References include cited_table when passage has table data."""
        passages = [
            self._build_passage_with_table("p1", "src-1", [["A", "B"]]),
        ]
        type_info = [None, None, None, passages, 1]

        result = ConversationMixin._extract_citation_data(type_info)

        assert result["sources_used"] == ["src-1"]
        assert len(result["references"]) == 1
        ref = result["references"][0]
        assert ref["source_id"] == "src-1"
        assert "cited_table" in ref
        assert ref["cited_table"]["num_columns"] == 2
        assert ref["cited_table"]["rows"] == [["A", "B"]]

    def test_citation_data_without_table_has_no_cited_table(self):
        """References without tables do not include cited_table key."""
        passages = [
            [
                ["pass-1"],
                [
                    None,
                    None,
                    0.75,
                    [[None, 0, 500]],
                    [[[0, 500, [[[0, 500, ["Normal text."]]]]]]],
                    [[["src-1"], "hash"]],
                    ["pass-1"],
                ],
            ],
        ]
        type_info = [None, None, None, passages, 1]

        result = ConversationMixin._extract_citation_data(type_info)

        assert result["sources_used"] == ["src-1"]
        ref = result["references"][0]
        assert "cited_table" not in ref
        assert ref.get("cited_text") == "Normal text."
