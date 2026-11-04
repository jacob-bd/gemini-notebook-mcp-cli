from unittest.mock import patch

from notebooklm_tools.mcp.tools import chats

SVC = "notebooklm_tools.services.chats.delete_chat_history"


def test_requires_confirmation():
    with patch(SVC) as service:
        result = chats.chat_delete(notebook_id="nb-123")

    service.assert_not_called()
    assert result["status"] == "error"
    assert "confirm" in result["error"].lower()


def test_confirmed_delete_returns_service_result():
    service_result = {
        "notebook_id": "nb-123",
        "notebook_title": "Test Notebook",
        "conversation_id": "conv-123",
        "message": "Chat history deleted.",
    }
    with patch(SVC, return_value=service_result) as service:
        result = chats.chat_delete(notebook_id="nb-123", confirm=True)

    service.assert_called_once_with(notebook="nb-123")
    assert result == {"status": "success", **service_result}


def test_service_error_becomes_error_result():
    with patch(SVC, side_effect=ValueError("failed")):
        result = chats.chat_delete(notebook_id="nb-123", confirm=True)

    assert result["status"] == "error"
    assert "failed" in result["error"]
