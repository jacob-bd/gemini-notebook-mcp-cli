"""Chat sessions service layer for Google NotebookLM.

Provides business logic for listing, retrieving, exporting, and converting
notebook chat sessions.
"""

import json
import logging
from pathlib import Path
from typing import Any

from notebooklm_tools.core.auth import AuthManager
from notebooklm_tools.core.client import NotebookLMClient
from notebooklm_tools.core.exceptions import AuthenticationError
from notebooklm_tools.services import chat as chat_service
from notebooklm_tools.services.errors import (
    NotFoundError,
    ValidationError,
)
from notebooklm_tools.services.notes import create_note
from notebooklm_tools.utils.config import get_config

logger = logging.getLogger(__name__)


def _get_client(profile: str | None = None) -> NotebookLMClient:
    """Get an authenticated NotebookLM client for a profile.

    Falls back to the configured default profile (`nlm login switch`) when
    none is given, matching cli/utils.get_client() and mcp/tools/_utils.get_client()
    — MCP tools don't expose a profile param, so this is the only thing that
    makes them respect a non-"default"-named active profile.
    """
    profile = profile or get_config().auth.default_profile
    auth = AuthManager(profile)
    if not auth.profile_exists():
        raise AuthenticationError(
            message=f"Profile '{profile}' not found",
            hint="Run 'nlm login' to authenticate.",
        )
    profile_data = auth.load_profile()
    return NotebookLMClient(
        cookies=profile_data.cookies,
        csrf_token=profile_data.csrf_token,
        session_id=profile_data.session_id,
        base_host=profile_data.base_host or "",
        profile_name=profile,
    )


def _resolve_notebook(client: NotebookLMClient, notebook: str) -> tuple[str, str]:
    """Resolve notebook name or ID to (notebook_id, notebook_title)."""
    notebooks = client.list_notebooks()
    target = None

    # Match exact ID
    for nb in notebooks:
        if getattr(nb, "id", "") == notebook:
            target = nb
            break

    # Match title (case-insensitive substring)
    if not target:
        matches = [nb for nb in notebooks if notebook.lower() in getattr(nb, "title", "").lower()]
        if len(matches) == 1:
            target = matches[0]
        elif len(matches) > 1:
            exact = [nb for nb in matches if getattr(nb, "title", "").lower() == notebook.lower()]
            if len(exact) == 1:
                target = exact[0]
            else:
                names = [
                    f"'{getattr(nb, 'title', '')}' ({getattr(nb, 'id', '')})" for nb in matches
                ]
                raise ValidationError(
                    f"Ambiguous notebook '{notebook}'. Matches multiple notebooks: {', '.join(names)}"
                )

    if not target:
        raise NotFoundError(
            message=f"Notebook '{notebook}' not found",
            resource_type="notebook",
            hint="Use 'nlm notebook list' to view available notebooks.",
        )

    return target.id, getattr(target, "title", "Untitled")


def _get_transcript(
    client: NotebookLMClient, notebook_id: str, conversation_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Get a conversation's turns, preferring the server over the local cache.

    `get_conversation_turns()` fetches real history from NotebookLM's server,
    so past chats are visible even on a fresh CLI invocation or MCP session.
    Falls back to the in-process cache (`get_conversation_history()`) only if
    the server call fails or returns nothing — e.g. for a conversation
    created moments ago in this same process.
    """
    turns = client.get_conversation_turns(notebook_id, conversation_id, limit=limit)
    if turns:
        return turns
    return client.get_conversation_history(conversation_id) or []


def list_chat_sessions(
    notebook: str,
    limit: int = 20,
    profile: str | None = None,
) -> dict[str, Any]:
    """List all chat sessions for a notebook.

    Args:
        notebook: Notebook ID or title alias
        limit: Max sessions to return (default: 20)
        profile: NLM profile name (default: configured default profile)

    Returns:
        Dict with notebook_id, notebook_title, and sessions list.
    """
    client = _get_client(profile)
    notebook_id, notebook_title = _resolve_notebook(client, notebook)

    # Fetch persistent conversation ID from server
    conv_id = client.get_conversation_id(notebook_id)
    sessions = []

    if conv_id:
        # `limit` here bounds the number of *sessions* returned (currently at
        # most 1, since a notebook has a single persistent conversation) —
        # it is unrelated to how many turns we fetch to compute turn_count,
        # so we don't pass it through to the turn fetch below.
        history = _get_transcript(client, notebook_id, conv_id)
        first_turn = history[0] if history else {}
        preview = first_turn.get("query", "Empty chat session")
        sessions.append(
            {
                "conversation_id": conv_id,
                "turn_count": len(history),
                "preview": preview,
                "is_active": True,
            }
        )

    return {
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "sessions": sessions[:limit],
    }


def get_chat_session(
    notebook: str,
    conversation_id: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Get details and transcript for a specific chat session.

    Args:
        notebook: Notebook ID or title alias
        conversation_id: Optional conversation ID. If None, retrieves latest session.
        profile: NLM profile name (default: configured default profile)

    Returns:
        Dict with conversation details and turn transcript.
    """
    client = _get_client(profile)
    notebook_id, notebook_title = _resolve_notebook(client, notebook)

    target_conv_id = conversation_id or client.get_conversation_id(notebook_id)
    if not target_conv_id:
        raise NotFoundError(
            message=f"No active chat session found for notebook '{notebook}'",
            resource_type="chat session",
            hint="No active chat session found for this notebook.",
        )

    history = _get_transcript(client, notebook_id, target_conv_id)

    return {
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "conversation_id": target_conv_id,
        "turn_count": len(history),
        "transcript": history,
    }


def delete_chat_history(
    notebook: str,
    profile: str | None = None,
    *,
    client: NotebookLMClient | None = None,
) -> dict[str, Any]:
    """Delete history using the caller's authenticated client when supplied."""
    if client is None:
        with _get_client(profile) as owned_client:
            return delete_chat_history(notebook, client=owned_client)
    notebook_id, notebook_title = _resolve_notebook(client, notebook)
    result = chat_service.delete_chat_history(client, notebook_id)
    return {**result, "notebook_title": notebook_title}


def export_chat_session(
    notebook: str,
    conversation_id: str | None = None,
    format: str = "md",
    output_file: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Export a chat session to Markdown or JSON.

    Args:
        notebook: Notebook ID or title alias
        conversation_id: Optional conversation ID
        format: Export format ("md" or "json", default: "md")
        output_file: Optional output file path
        profile: NLM profile name (default: configured default profile)

    Returns:
        Dict with status, content, and file path if written.
    """
    session_data = get_chat_session(notebook, conversation_id, profile)
    fmt = format.lower()
    if fmt not in ("md", "json", "markdown"):
        raise ValidationError(f"Unsupported format '{format}'. Allowed formats: 'md', 'json'.")

    if fmt == "json":
        content = json.dumps(session_data, indent=2, ensure_ascii=False)
    else:
        title = session_data["notebook_title"]
        conv_id = session_data["conversation_id"]
        lines = [f"# Chat History - {title}", f"**Session ID**: `{conv_id}`\n"]
        for turn in session_data["transcript"]:
            t_num = turn.get("turn", 1)
            q = turn.get("query", "")
            a = turn.get("answer", "")
            lines.append(f"## Turn {t_num}")
            lines.append(f"**User**: {q}\n")
            lines.append(f"**NotebookLM**: {a}\n")
        content = "\n".join(lines)

    saved_path = None
    if output_file:
        path = Path(output_file).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        saved_path = str(path)

    return {
        "status": "success",
        "notebook_id": session_data["notebook_id"],
        "conversation_id": session_data["conversation_id"],
        "format": fmt,
        "content": content,
        "file_path": saved_path,
    }


def save_chat_to_note(
    notebook: str,
    conversation_id: str,
    turn_index: int | None = None,
    title: str | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    """Save a chat turn or full chat session as a Note in the notebook.

    Args:
        notebook: Notebook ID or title alias
        conversation_id: Conversation ID
        turn_index: Optional 1-indexed turn to save. If None, saves full chat.
        title: Optional note title
        profile: NLM profile name

    Returns:
        Dict with created note details.
    """
    session_data = get_chat_session(notebook, conversation_id, profile)
    transcript = session_data["transcript"]
    if not transcript:
        raise ValidationError("Cannot save empty chat session to Note.")

    if turn_index is not None:
        turns = [t for t in transcript if t.get("turn") == turn_index]
        if not turns:
            raise ValidationError(f"Turn {turn_index} not found in conversation.")
        target_turns = turns
    else:
        target_turns = transcript

    note_title = title or f"Chat Note - {session_data['notebook_title']}"
    content_lines = []
    for turn in target_turns:
        content_lines.append(f"**Q**: {turn.get('query', '')}\n\n**A**: {turn.get('answer', '')}\n")

    content = "\n---\n".join(content_lines)

    # create_note() takes an authenticated client + resolved notebook_id (not
    # a notebook alias/profile pair), so build a client for it directly.
    client = _get_client(profile)
    notebook_id = session_data["notebook_id"]
    return create_note(client, notebook_id, content, note_title)
