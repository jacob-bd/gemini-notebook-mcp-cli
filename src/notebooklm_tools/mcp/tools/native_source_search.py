"""Experimental native NotebookLM source passage retrieval MCP tool.

Deliberately registered without logged_tool: the normal debug wrapper serializes
response bodies, which would expose private source passages in diagnostics.
"""

from __future__ import annotations

import os
from typing import Any

from notebooklm_tools.services.source_search import SourceSearchError, search_native_sources

from ._utils import error_result, get_client, unlogged_tool


@unlogged_tool()
def source_search(
    notebook_id: str,
    query: str,
    source_ids: list[str] | None = None,
    max_results: int = 8,
    snippet_chars: int = 900,
) -> dict[str, Any]:
    """Search relevant indexed passages within one NotebookLM notebook (read-only).

    Optional source_ids restrict retrieval to sources belonging to this notebook.
    Returns at most 20 excerpted passages with native source UUIDs and titles.
    No Gemini or Opal credentials are used. Experimental, off by default.

    Set NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH=1 in the server environment.
    """
    if os.environ.get("NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH") != "1":
        return error_result(
            "Native source search is experimental and disabled",
            hint="Set NOTEBOOKLM_ENABLE_NATIVE_SOURCE_SEARCH=1 in the MCP server environment.",
        )
    try:
        result = search_native_sources(
            get_client(), notebook_id, query, source_ids, max_results, snippet_chars
        )
        return {"status": "success", **result}
    except SourceSearchError as error:
        return error_result(str(error))
    except Exception:
        # Never serialize HTTP exceptions, URLs, RPC bodies, or source data.
        return error_result("Native source retrieval failed; check session and notebook access")
