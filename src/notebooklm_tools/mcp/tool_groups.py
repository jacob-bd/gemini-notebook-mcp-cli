"""Optional group-based gating of MCP tools.

The server registers a large tool set (43 tools). Clients that only need a
subset can hide the rest to save context, without editing code, by toggling
named groups or individual tools through environment variables.

Gating is opt-in: with no configuration, every tool stays visible and behavior
is unchanged.

Resolution order (later wins for a given tool):
  1. env NOTEBOOKLM_DISABLED_GROUPS (comma-separated group names) hides whole
     groups.
  2. env NOTEBOOKLM_DISABLED_TOOLS (comma-separated tool names) hides single
     tools.
  3. env NOTEBOOKLM_ENABLED_TOOLS (comma-separated tool names) re-enables single
     tools, overriding the two above.

apply(mcp) is called once from server._register_tools() after all tools are
registered. It uses FastMCP's visibility transform
(mcp.local_provider.disable(names=...)) so no tool is unregistered, only hidden.
"""

from __future__ import annotations

import os
from typing import Any

# Read/manage split so a query-first client can hide mutating tools while
# keeping the read + chat core. Each tool name appears in exactly one group;
# together the groups cover every registered tool.
TOOL_GROUPS: dict[str, set[str]] = {
    "notebooks_read": {
        "notebook_list",
        "notebook_get",
        "notebook_describe",
    },
    "notebooks_manage": {
        "notebook_create",
        "notebook_rename",
        "notebook_delete",
    },
    "sources_read": {
        "source_list_drive",
        "source_describe",
        "source_get_content",
    },
    "sources_manage": {
        "source_add",
        "source_rename",
        "source_delete",
        "source_sync_drive",
    },
    "chat": {
        "notebook_query",
        "chat_configure",
        "notebook_query_start",
        "notebook_query_status",
        "chat_list",
        "chat_get",
        "chat_export",
    },
    "query_multi": {
        "cross_notebook_query",
    },
    "organization": {
        "label",
        "tag",
        "collection_list",
        "collection_create",
        "collection_edit",
        "collection_set_emoji",
        "collection_delete",
    },
    "automation": {
        "batch",
        "pipeline",
    },
    "notes": {
        "note",
    },
    "auth": {
        "refresh_auth",
        "save_auth_tokens",
    },
    "server": {
        "server_info",
    },
    "sharing": {
        "notebook_share_status",
        "notebook_share_public",
        "notebook_share_invite",
        "notebook_share_batch",
    },
    "research": {
        "research_start",
        "research_status",
        "research_import",
    },
    "studio": {
        "studio_create",
        "studio_status",
        "studio_delete",
        "studio_revise",
        "download_artifact",
        "download_all_artifacts",
        "export_artifact",
    },
}


def _env_names(var: str) -> set[str]:
    raw = os.environ.get(var, "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _resolve_disabled() -> set[str]:
    """Compute the final set of tool names to hide (empty unless configured)."""
    names: set[str] = set()
    for group in _env_names("NOTEBOOKLM_DISABLED_GROUPS"):
        names |= TOOL_GROUPS.get(group, set())

    names |= _env_names("NOTEBOOKLM_DISABLED_TOOLS")
    names -= _env_names("NOTEBOOKLM_ENABLED_TOOLS")
    return names


def apply(mcp: Any) -> set[str]:
    """Hide the resolved set of tools on the given FastMCP instance.

    Returns the set of hidden tool names (empty if nothing was hidden).
    """
    names = _resolve_disabled()
    if names:
        mcp.local_provider.disable(names=names)
    return names
