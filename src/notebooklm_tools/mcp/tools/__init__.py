"""MCP tools - Modular tool definitions for the Gemini Notebook MCP server."""

# Import all tools from submodules for registration
from .auth import refresh_auth, save_auth_tokens
from .batch import batch
from .chat import (
    chat_configure,
    notebook_query,
    notebook_query_start,
    notebook_query_status,
)
from .chats import chat_export, chat_get, chat_list
from .cross_notebook import cross_notebook_query
from .downloads import download_all_artifacts, download_artifact
from .exports import (
    export_artifact,
)
from .labels import label
from .notebooks import (
    notebook_create,
    notebook_delete,
    notebook_describe,
    notebook_get,
    notebook_list,
    notebook_rename,
)
from .notes import note
from .pipeline import pipeline
from .research import (
    research_import,
    research_start,
    research_status,
)
from .server import server_info
from .sharing import (
    notebook_share_batch,
    notebook_share_invite,
    notebook_share_public,
    notebook_share_status,
)
from .smart_select import tag
from .sources import (
    source_add,
    source_delete,
    source_describe,
    source_get_content,
    source_list_drive,
    source_rename,
    source_sync_drive,
)
from .studio import (
    studio_create,
    studio_delete,
    studio_revise,
    studio_status,
)

__all__ = [
    # Downloads (1 consolidated + 1 bulk)
    "download_artifact",
    "download_all_artifacts",
    # Auth (2)
    "refresh_auth",
    "save_auth_tokens",
    # Notebooks (6)
    "notebook_list",
    "notebook_get",
    "notebook_describe",
    "notebook_create",
    "notebook_rename",
    "notebook_delete",
    # Sources (7)
    "source_add",
    "source_list_drive",
    "source_sync_drive",
    "source_delete",
    "source_describe",
    "source_get_content",
    "source_rename",
    # Sharing (4)
    "notebook_share_status",
    "notebook_share_public",
    "notebook_share_invite",
    "notebook_share_batch",
    # Research (3)
    "research_start",
    "research_status",
    "research_import",
    # Studio (4 - consolidated create + revise + list_types via status)
    "studio_create",
    "studio_status",
    "studio_delete",
    "studio_revise",
    # Chat (7)
    "notebook_query",
    "notebook_query_start",
    "notebook_query_status",
    "chat_configure",
    "chat_list",
    "chat_get",
    "chat_export",
    # Exports (1)
    "export_artifact",
    # Notes (1 consolidated)
    "note",
    # Labels (1 consolidated — action: auto|list|reorganize|create|rename|set_emoji|move_source|delete)
    "label",
    # Server (1)
    "server_info",
    # Batch (1 consolidated — action: query|add_source|create|delete|studio)
    "batch",
    # Cross-notebook (1)
    "cross_notebook_query",
    # Pipeline (1 consolidated — action: run|list)
    "pipeline",
    # Tag/Smart Select (1 consolidated — action: add|remove|list|select)
    "tag",
]
