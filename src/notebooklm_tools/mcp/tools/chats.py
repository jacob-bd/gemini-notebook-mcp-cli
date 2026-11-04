"""MCP tools for notebook chat sessions."""

from notebooklm_tools.mcp.tools._utils import ResultDict, error_result, get_client, logged_tool
from notebooklm_tools.services import chats


@logged_tool()
def chat_list(
    notebook_id: str,
    limit: int = 20,
) -> ResultDict:
    """List chat sessions for a notebook.

    Args:
        notebook_id: Notebook ID or title alias
        limit: Max chat sessions to return (default: 20)
    """
    try:
        data = chats.list_chat_sessions(notebook=notebook_id, limit=limit)
        return {
            "status": "success",
            "notebook_id": data["notebook_id"],
            "notebook_title": data["notebook_title"],
            "sessions": data["sessions"],
        }
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def chat_get(
    notebook_id: str,
    conversation_id: str = "",
) -> ResultDict:
    """Get full transcript of a specific chat session.

    Args:
        notebook_id: Notebook ID or title alias
        conversation_id: Optional conversation ID (defaults to latest active session)
    """
    try:
        conv_id = conversation_id if conversation_id else None
        data = chats.get_chat_session(notebook=notebook_id, conversation_id=conv_id)
        return {
            "status": "success",
            "notebook_id": data["notebook_id"],
            "notebook_title": data["notebook_title"],
            "conversation_id": data["conversation_id"],
            "turn_count": data["turn_count"],
            "transcript": data["transcript"],
        }
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def chat_export(
    notebook_id: str,
    conversation_id: str = "",
    format: str = "md",
) -> ResultDict:
    """Export a chat transcript to Markdown or JSON.

    Args:
        notebook_id: Notebook ID or title alias
        conversation_id: Optional conversation ID
        format: Export format: 'md' or 'json' (default: 'md')
    """
    try:
        conv_id = conversation_id if conversation_id else None
        data = chats.export_chat_session(
            notebook=notebook_id, conversation_id=conv_id, format=format
        )
        return {
            "status": "success",
            "notebook_id": data["notebook_id"],
            "conversation_id": data["conversation_id"],
            "format": data["format"],
            "content": data["content"],
        }
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def chat_save_to_note(
    notebook_id: str,
    conversation_id: str,
    turn: int = 0,
    title: str = "",
) -> ResultDict:
    """Save a chat (or one turn of it) as a Note in the notebook.

    Args:
        notebook_id: Notebook ID or title alias
        conversation_id: Conversation ID (see chat_list)
        turn: 1-indexed turn to save; 0 (default) saves the whole chat
        title: Optional note title
    """
    try:
        data = chats.save_chat_to_note(
            notebook=notebook_id,
            conversation_id=conversation_id,
            turn_index=turn or None,
            title=title or None,
        )
        return {"status": "success", **data}
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def chat_delete(
    notebook_id: str,
    confirm: bool = False,
) -> ResultDict:
    """Permanently delete all chat history for a notebook. Requires confirmation.

    Args:
        notebook_id: Notebook ID or title alias
        confirm: Must be True after user approval
    """
    if not confirm:
        return error_result(
            "Deletion not confirmed. Set confirm=True after user approval.",
            warning="This action is IRREVERSIBLE. All chat history will be permanently deleted.",
        )

    try:
        data = chats.delete_chat_history(notebook=notebook_id, client=get_client())
        return {"status": "success", **data}
    except Exception as e:
        return error_result(str(e))
