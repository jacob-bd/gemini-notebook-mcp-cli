"""Unit tests for the chats service layer (TDD)."""

from unittest.mock import MagicMock, patch

import pytest

from notebooklm_tools.services import chats
from notebooklm_tools.services.errors import NotFoundError, ValidationError


class TestChatsService:
    """TDD tests for notebook chat sessions service."""

    @patch("notebooklm_tools.services.chats.chat_service.delete_chat_history")
    @patch("notebooklm_tools.services.chats._resolve_notebook")
    @patch("notebooklm_tools.services.chats._get_client")
    def test_delete_chat_history_resolves_notebook_and_profile(
        self, mock_get_client, mock_resolve_notebook, mock_delete_chat
    ):
        client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = client
        mock_resolve_notebook.return_value = ("nb-123", "Test Notebook")
        mock_delete_chat.return_value = {
            "notebook_id": "nb-123",
            "conversation_id": "conv-123",
            "message": "Chat history deleted.",
        }

        result = chats.delete_chat_history("my notebook", profile="work")

        mock_get_client.assert_called_once_with("work")
        mock_resolve_notebook.assert_called_once_with(client, "my notebook")
        mock_delete_chat.assert_called_once_with(client, "nb-123")
        assert result["notebook_title"] == "Test Notebook"
        assert result["conversation_id"] == "conv-123"

    @patch("notebooklm_tools.services.chats.AuthManager")
    @patch("notebooklm_tools.services.chats.NotebookLMClient")
    def test_list_chat_sessions_success(self, mock_client_cls, mock_auth_cls):
        mock_auth = MagicMock()
        mock_auth.profile_exists.return_value = True
        mock_auth.load_profile.return_value = MagicMock(
            cookies={"SID": "123"}, csrf_token="at", session_id="sid"
        )
        mock_auth_cls.return_value = mock_auth

        mock_client = MagicMock()
        mock_client.list_notebooks.return_value = [MagicMock(id="nb-123", title="Test Notebook")]
        mock_client.get_conversation_id.return_value = "conv-abc-123"
        mock_client.get_conversation_turns.return_value = [
            {"turn": 1, "query": "What is AI?", "answer": "Artificial Intelligence"}
        ]
        # Local cache should not be consulted when the server has turns.
        mock_client.get_conversation_history.return_value = None
        mock_client_cls.return_value = mock_client

        result = chats.list_chat_sessions(notebook="nb-123", profile="default")

        assert result["notebook_id"] == "nb-123"
        assert result["notebook_title"] == "Test Notebook"
        assert len(result["sessions"]) == 1
        assert result["sessions"][0]["conversation_id"] == "conv-abc-123"
        assert result["sessions"][0]["turn_count"] == 1
        mock_client.get_conversation_history.assert_not_called()

    @patch("notebooklm_tools.services.chats.AuthManager")
    @patch("notebooklm_tools.services.chats.NotebookLMClient")
    def test_list_chat_sessions_falls_back_to_cache(self, mock_client_cls, mock_auth_cls):
        """When the server returns no turns (e.g. RPC failure), fall back to the
        in-process cache rather than reporting an empty session."""
        mock_auth = MagicMock()
        mock_auth.profile_exists.return_value = True
        mock_auth.load_profile.return_value = MagicMock(
            cookies={"SID": "123"}, csrf_token="at", session_id="sid"
        )
        mock_auth_cls.return_value = mock_auth

        mock_client = MagicMock()
        mock_client.list_notebooks.return_value = [MagicMock(id="nb-123", title="Test Notebook")]
        mock_client.get_conversation_id.return_value = "conv-abc-123"
        mock_client.get_conversation_turns.return_value = None
        mock_client.get_conversation_history.return_value = [
            {"turn": 1, "query": "Cached question", "answer": "Cached answer"}
        ]
        mock_client_cls.return_value = mock_client

        result = chats.list_chat_sessions(notebook="nb-123", profile="default")

        assert result["sessions"][0]["preview"] == "Cached question"
        assert result["sessions"][0]["turn_count"] == 1

    @patch("notebooklm_tools.services.chats.AuthManager")
    @patch("notebooklm_tools.services.chats.NotebookLMClient")
    def test_get_chat_session_not_found(self, mock_client_cls, mock_auth_cls):
        mock_auth = MagicMock()
        mock_auth.profile_exists.return_value = True
        mock_auth.load_profile.return_value = MagicMock(
            cookies={"SID": "123"}, csrf_token="at", session_id="sid"
        )
        mock_auth_cls.return_value = mock_auth

        mock_client = MagicMock()
        mock_client.list_notebooks.return_value = []
        mock_client_cls.return_value = mock_client

        with pytest.raises(NotFoundError):
            chats.get_chat_session(notebook="nonexistent-notebook")

    @patch("notebooklm_tools.services.chats.AuthManager")
    @patch("notebooklm_tools.services.chats.NotebookLMClient")
    def test_export_chat_session_markdown(self, mock_client_cls, mock_auth_cls):
        mock_auth = MagicMock()
        mock_auth.profile_exists.return_value = True
        mock_auth.load_profile.return_value = MagicMock(
            cookies={"SID": "123"}, csrf_token="at", session_id="sid"
        )
        mock_auth_cls.return_value = mock_auth

        mock_client = MagicMock()
        mock_client.list_notebooks.return_value = [MagicMock(id="nb-123", title="Test Notebook")]
        mock_client.get_conversation_id.return_value = "conv-abc-123"
        mock_client.get_conversation_turns.return_value = [
            {"turn": 1, "query": "What is AI?", "answer": "Artificial Intelligence"}
        ]
        mock_client.get_conversation_history.return_value = None
        mock_client_cls.return_value = mock_client

        result = chats.export_chat_session(notebook="nb-123", format="md")

        assert result["status"] == "success"
        assert "## Turn 1" in result["content"]
        assert "What is AI?" in result["content"]
        assert "Artificial Intelligence" in result["content"]

    @patch("notebooklm_tools.services.chats.create_note")
    @patch("notebooklm_tools.services.chats.AuthManager")
    @patch("notebooklm_tools.services.chats.NotebookLMClient")
    def test_save_chat_to_note_calls_create_note_correctly(
        self, mock_client_cls, mock_auth_cls, mock_create_note
    ):
        """create_note() takes (client, notebook_id, content, title) — not the
        notebook alias/profile kwargs save_chat_to_note used to pass, which
        would have raised a TypeError at runtime."""
        mock_auth = MagicMock()
        mock_auth.profile_exists.return_value = True
        mock_auth.load_profile.return_value = MagicMock(
            cookies={"SID": "123"}, csrf_token="at", session_id="sid"
        )
        mock_auth_cls.return_value = mock_auth

        mock_client = MagicMock()
        mock_client.list_notebooks.return_value = [MagicMock(id="nb-123", title="Test Notebook")]
        mock_client.get_conversation_id.return_value = "conv-abc-123"
        mock_client.get_conversation_turns.return_value = [
            {"turn": 1, "query": "What is AI?", "answer": "Artificial Intelligence"}
        ]
        mock_client_cls.return_value = mock_client
        mock_create_note.return_value = {
            "note_id": "note-1",
            "title": "Chat Note - Test Notebook",
            "content_preview": "...",
            "message": "Created",
        }

        result = chats.save_chat_to_note(notebook="nb-123", conversation_id="conv-abc-123")

        mock_create_note.assert_called_once()
        args = mock_create_note.call_args.args
        assert args[0] is mock_client
        assert args[1] == "nb-123"
        assert "What is AI?" in args[2]
        assert result["note_id"] == "note-1"

    @patch("notebooklm_tools.services.chats.AuthManager")
    @patch("notebooklm_tools.services.chats.NotebookLMClient")
    def test_save_chat_to_note_rejects_empty_transcript(self, mock_client_cls, mock_auth_cls):
        mock_auth = MagicMock()
        mock_auth.profile_exists.return_value = True
        mock_auth.load_profile.return_value = MagicMock(
            cookies={"SID": "123"}, csrf_token="at", session_id="sid"
        )
        mock_auth_cls.return_value = mock_auth

        mock_client = MagicMock()
        mock_client.list_notebooks.return_value = [MagicMock(id="nb-123", title="Test Notebook")]
        mock_client.get_conversation_id.return_value = "conv-abc-123"
        mock_client.get_conversation_turns.return_value = None
        mock_client.get_conversation_history.return_value = None
        mock_client_cls.return_value = mock_client

        with pytest.raises(ValidationError):
            chats.save_chat_to_note(notebook="nb-123", conversation_id="conv-abc-123")


def test_delete_uses_injected_client_without_loading_another_profile():
    client = MagicMock()
    with (
        patch("notebooklm_tools.services.chats._get_client") as load,
        patch(
            "notebooklm_tools.services.chats._resolve_notebook", return_value=("nb-123", "Notebook")
        ),
        patch(
            "notebooklm_tools.services.chats.chat_service.delete_chat_history",
            return_value={"notebook_id": "nb-123", "conversation_id": "conv-123"},
        ) as delete,
    ):
        chats.delete_chat_history("Notebook", client=client)
    load.assert_not_called()
    delete.assert_called_once_with(client, "nb-123")
