"""Every CLI command maps to an MCP tool or is deliberately CLI-only."""

import click
import typer

from notebooklm_tools.cli.main import app
from notebooklm_tools.mcp import server  # noqa: F401  (registers tools)
from notebooklm_tools.mcp.tools import _utils

CLI_ONLY = "CLI_ONLY"
STUDIO = "studio_create"

MAPPING = {
    "add drive": "source_add",
    "add text": "source_add",
    "add url": "source_add",
    "alias delete": "alias",
    "alias get": "alias",
    "alias list": "alias",
    "alias set": "alias",
    "audio create": STUDIO,
    "auth refresh": "refresh_auth",
    "auth storage status": "profile",
    "auth storage set": CLI_ONLY,
    "auth storage resolve": CLI_ONLY,
    "auth storage relocate": CLI_ONLY,
    "batch add-source": "batch",
    "batch create": "batch",
    "batch delete": "batch",
    "batch query": "batch",
    "batch studio": "batch",
    "chat configure": "chat_configure",
    "chat start": CLI_ONLY,
    "chats export": "chat_export",
    "chats delete": "chat_delete",
    "chats get": "chat_get",
    "chats list": "chat_list",
    "chats to-note": "chat_save_to_note",
    "config get": CLI_ONLY,
    "config set": CLI_ONLY,
    "config show": CLI_ONLY,
    "configure chat": "chat_configure",
    "content source": "source_get_content",
    "create audio": STUDIO,
    "create data-table": STUDIO,
    "create flashcards": STUDIO,
    "create infographic": STUDIO,
    "create mindmap": STUDIO,
    "create quiz": STUDIO,
    "create report": STUDIO,
    "create slides": STUDIO,
    "create video": STUDIO,
    "create notebook": "notebook_create",
    "cross query": "cross_notebook_query",
    "data-table create": STUDIO,
    "delete alias": "alias",
    "delete artifact": "studio_delete",
    "delete notebook": "notebook_delete",
    "delete source": "source_delete",
    "describe notebook": "notebook_describe",
    "describe source": "source_describe",
    "doctor": "server_info",
    "doctor auth-replay": CLI_ONLY,
    **{
        f"download {t}": "download_artifact"
        for t in (
            "audio",
            "data-table",
            "file",
            "flashcards",
            "infographic",
            "mind-map",
            "quiz",
            "report",
            "slide-deck",
            "video",
        )
    },
    "download all": "download_all_artifacts",
    "export artifact": "export_artifact",
    "export to-docs": "export_artifact",
    "export to-sheets": "export_artifact",
    "flashcards create": STUDIO,
    "get alias": "alias",
    "get config": CLI_ONLY,
    "get notebook": "notebook_get",
    "get source": "source_describe",
    "infographic create": STUDIO,
    "install skill": CLI_ONLY,
    **{
        f"label {a}": "label"
        for a in ("auto", "create", "delete", "emoji", "list", "move", "rename", "reorganize")
    },
    "list aliases": "alias",
    "list artifacts": "studio_status",
    "list notebooks": "notebook_list",
    "list skills": CLI_ONLY,
    "list sources": "notebook_get",
    "list stale-sources": "source_list_drive",
    "login": CLI_ONLY,
    "login profile delete": CLI_ONLY,
    "login profile rename": CLI_ONLY,
    "login profile list": "profile",
    "login switch": "profile",
    "mindmap create": STUDIO,
    "note create": "note",
    "note delete": "note",
    "note list": "note",
    "note update": "note",
    "notebook create": "notebook_create",
    "notebook delete": "notebook_delete",
    "notebook describe": "notebook_describe",
    "notebook get": "notebook_get",
    "notebook list": "notebook_list",
    "notebook query": "notebook_query",
    "notebook rename": "notebook_rename",
    "pipeline create": "pipeline",
    "pipeline list": "pipeline",
    "pipeline run": "pipeline",
    "query notebook": "notebook_query",
    "quiz create": STUDIO,
    "rename notebook": "notebook_rename",
    "rename source": "source_rename",
    "rename studio": "studio_status",
    "report create": STUDIO,
    "report element create": "report",
    "report element create-batch": "report",
    "report elements": "report",
    "report get": "report",
    "research import": "research_import",
    "research start": "research_start",
    "research status": "research_status",
    "set alias": "alias",
    "set config": CLI_ONLY,
    "setup": CLI_ONLY,
    "setup add": CLI_ONLY,
    "setup list": CLI_ONLY,
    "setup remove": CLI_ONLY,
    "share batch": "notebook_share_batch",
    "share invite": "notebook_share_invite",
    "share private": "notebook_share_public",
    "share public": "notebook_share_public",
    "share status": "notebook_share_status",
    "show aliases": "alias",
    "show config": CLI_ONLY,
    "show skill": CLI_ONLY,
    **{
        f"skill {a}": CLI_ONLY
        for a in ("install", "list", "package", "show", "uninstall", "update")
    },
    "slides create": STUDIO,
    "slides revise": "studio_revise",
    "source add": "source_add",
    "source content": "source_get_content",
    "source delete": "source_delete",
    "source describe": "source_describe",
    "source get": "source_describe",
    "source list": "notebook_get",
    "source rename": "source_rename",
    "source stale": "source_list_drive",
    "source sync": "source_sync_drive",
    "stale sources": "source_list_drive",
    "status artifacts": "studio_status",
    "status research": "research_status",
    "studio delete": "studio_delete",
    "studio rename": "studio_status",
    "studio status": "studio_status",
    "sync sources": "source_sync_drive",
    "tag add": "tag",
    "tag list": "tag",
    "tag remove": "tag",
    "tag select": "tag",
    "uninstall skill": CLI_ONLY,
    "update skill": CLI_ONLY,
    "usage": "usage_get",
    "video create": STUDIO,
    "video list": "studio_status",
}


def _cli_commands() -> set[str]:
    out: set[str] = set()

    def walk(cmd, path):
        if isinstance(cmd, click.Group):
            if path and cmd.invoke_without_command and cmd.callback:
                out.add(" ".join(path))
            for name, sub in cmd.commands.items():
                walk(sub, path + [name])
        else:
            out.add(" ".join(path))

    walk(typer.main.get_command(app), [])
    return out


def test_every_cli_command_is_mapped():
    unmapped = sorted(_cli_commands() - MAPPING.keys())
    assert not unmapped, f"New CLI commands need an MCP tool or CLI_ONLY entry: {unmapped}"


def test_mapping_has_no_stale_commands():
    stale = sorted(MAPPING.keys() - _cli_commands())
    assert not stale, f"Mapped commands no longer exist in the CLI: {stale}"


def test_every_mapped_tool_is_registered():
    registered = {n for n, _ in _utils._tool_registry}
    missing = sorted({t for t in MAPPING.values() if t != CLI_ONLY} - registered)
    assert not missing, f"Mapped MCP tools not registered: {missing}"
