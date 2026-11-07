"""Read-only Gemini conversation discovery, via the selected NotebookLM Google session.

Experimental and off by default. Never logs private titles or session tokens.
"""

from __future__ import annotations

import os
from typing import Any

from notebooklm_tools.services.errors import ServiceError
from notebooklm_tools.services.gemini_conversations import list_gemini_notebook_conversations

from ._utils import error_result, get_client, unlogged_tool


@unlogged_tool()
def gemini_notebook_conversation_list(
    notebook_id: str,
    limit: int = 10,
    gemini_account_index: int = 0,
) -> dict[str, Any]:
    """List Gemini conversations attached to a NotebookLM notebook (read-only).

    Reuses the selected NotebookLM Google session. Verifies overlapping native
    source UUIDs before disclosing notebook-scoped Gemini conversation titles.
    This does not retrieve transcripts or alter native NotebookLM chat history.
    Requires NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS=1 in the MCP environment.
    """
    if os.environ.get("NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS") != "1":
        return error_result(
            "Experimental Gemini conversation discovery is disabled",
            hint="Set NOTEBOOKLM_ENABLE_GEMINI_CONVERSATIONS=1 in the MCP environment.",
        )
    try:
        result = list_gemini_notebook_conversations(
            get_client(),
            notebook_id,
            limit=limit,
            gemini_account_index=gemini_account_index,
        )
        return {"status": "success", **result}
    except ServiceError as exc:
        return error_result(str(exc))
    except Exception:
        # Never surface HTTP exception messages, URLs, request payloads or tokens.
        return error_result("Gemini conversation discovery failed; verify account and session")
