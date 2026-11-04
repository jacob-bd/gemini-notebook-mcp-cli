"""Unit tests for the chats CLI commands."""

from unittest.mock import patch

from typer.testing import CliRunner

from notebooklm_tools.cli.main import app

runner = CliRunner()


class TestChatsCLI:
    """CLI tests for chat session commands."""

    @patch("notebooklm_tools.services.chats.list_chat_sessions")
    def test_chats_list_json(self, mock_list_chats):
        mock_list_chats.return_value = {
            "notebook_id": "nb-123",
            "notebook_title": "Test Notebook",
            "sessions": [
                {
                    "conversation_id": "conv-123",
                    "turn_count": 2,
                    "preview": "First question?",
                    "is_active": True,
                }
            ],
        }

        result = runner.invoke(app, ["chats", "list", "nb-123", "--json"])

        assert result.exit_code == 0
        assert "conv-123" in result.stdout
        assert "Test Notebook" in result.stdout

    @patch("notebooklm_tools.services.chats.get_chat_session")
    def test_chats_get_json(self, mock_get_chat):
        mock_get_chat.return_value = {
            "notebook_id": "nb-123",
            "notebook_title": "Test Notebook",
            "conversation_id": "conv-123",
            "turn_count": 1,
            "transcript": [{"turn": 1, "query": "Hello?", "answer": "Hi there!"}],
        }

        result = runner.invoke(app, ["chats", "get", "nb-123", "conv-123", "--json"])

        assert result.exit_code == 0
        assert "conv-123" in result.stdout
        assert "Hello?" in result.stdout

    @patch("notebooklm_tools.services.chats.export_chat_session")
    def test_chats_export_markdown(self, mock_export_chat):
        mock_export_chat.return_value = {
            "status": "success",
            "notebook_id": "nb-123",
            "conversation_id": "conv-123",
            "format": "md",
            "content": "# Chat History - Test Notebook\n\n## Turn 1\n**User**: Hello?",
            "file_path": None,
        }

        result = runner.invoke(app, ["chats", "export", "nb-123", "--format", "md"])

        assert result.exit_code == 0
        assert "Chat History - Test Notebook" in result.stdout

    @patch("notebooklm_tools.services.chats.delete_chat_history")
    def test_chats_delete_requires_confirmation(self, mock_delete_chat):
        result = runner.invoke(app, ["chats", "delete", "nb-123"], input="n\n")

        assert result.exit_code != 0
        mock_delete_chat.assert_not_called()

    @patch("notebooklm_tools.services.chats.delete_chat_history")
    def test_chats_delete_confirmed(self, mock_delete_chat):
        mock_delete_chat.return_value = {
            "notebook_id": "nb-123",
            "notebook_title": "Test Notebook",
            "conversation_id": "conv-123",
            "message": "Chat history deleted.",
        }

        result = runner.invoke(
            app,
            ["chats", "delete", "nb-123", "--confirm", "--profile", "work"],
        )

        assert result.exit_code == 0
        assert "Deleted chat history for Test Notebook" in result.stdout
        mock_delete_chat.assert_called_once_with(notebook="nb-123", profile="work")

    @patch("notebooklm_tools.services.chats.delete_chat_history")
    def test_chats_delete_json(self, mock_delete_chat):
        mock_delete_chat.return_value = {
            "notebook_id": "nb-123",
            "notebook_title": "Test Notebook",
            "conversation_id": "conv-123",
            "message": "Chat history deleted.",
        }

        result = runner.invoke(
            app,
            ["chats", "delete", "nb-123", "--confirm", "--json"],
        )

        assert result.exit_code == 0
        assert '"conversation_id": "conv-123"' in result.stdout
