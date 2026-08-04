"""Gemini Notebook MCP Server - Modular Architecture.

This is the main server facade that initializes FastMCP and registers all tools
from the modular tools package. Tools are organized into domain-specific modules
under the `tools/` directory.

Tool Modules:
- auth.py: Authentication management (refresh_auth, save_auth_tokens)
- notebooks.py: Notebook CRUD operations
- sources.py: Source management with consolidated source_add
- sharing.py: Sharing and collaboration
- research.py: Deep research and source discovery
- studio.py: Artifact creation with consolidated studio_create
- downloads.py: Artifact downloads with consolidated download_artifact
- chat.py: Query and conversation management
- exports.py: Export artifacts to Google Docs/Sheets
- notes.py: Note management (create, list, update, delete)
"""

import argparse
import logging
import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from notebooklm_tools import __version__

_FALSY = frozenset({"false", "0", "no", "off"})


def _env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean from an environment variable. Unset/empty → *default*; otherwise ``false|0|no|off`` (case-insensitive) → False, anything else → True."""
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.lower() not in _FALSY


# Initialize MCP server
mcp = FastMCP(
    name="gemini-notebook-mcp",
    instructions="""Gemini Notebook MCP - Access Gemini Notebook (notebook.google.com).

**Auth:** If you get authentication errors, run `nlm login` via your Bash/terminal tool. This is the automated authentication method that handles everything. Only use save_auth_tokens as a fallback if the CLI fails.
**Account Switching:** To switch Google Accounts for the MCP server, run `nlm login switch <profile>` in Bash. The MCP server instantly uses the active default profile.
**Confirmation:** Tools with confirm param require user approval before setting confirm=True.
**Studio:** After creating audio/video/infographic/slides, poll studio_status for completion.

Consolidated tools:
- source_add(source_type=url|text|drive|file, url=..., document_id=..., text=..., file_path=...): Add any source type
- studio_create(artifact_type=audio|video|...): Create any artifact type
- studio_revise: Revise individual slides in an existing slide deck
- download_artifact(artifact_type=audio|video|...): Download any artifact type
- download_all_artifacts: Download every completed artifact of a notebook into a per-notebook folder
- note(action=create|list|update|delete): Manage notes in notebooks
- label(action=auto|list|reorganize|create|rename|set_emoji|move_source|delete): Manage source labels""",
)

# MCP request/response logger
mcp_logger = logging.getLogger("notebooklm_tools.mcp")


# Health check endpoint
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint for load balancers and monitoring."""
    return JSONResponse(
        {
            "status": "healthy",
            "service": "gemini-notebook-mcp",
            "version": __version__,
        }
    )


def _register_tools() -> None:
    """Import and register all tools from the modular tools package."""
    # Import all tool modules to populate the registry
    from .tools import (  # noqa: F401
        auth,
        batch,
        chat,
        chats,
        cross_notebook,
        downloads,
        exports,
        labels,
        notebooks,
        notes,
        pipeline,
        research,
        sharing,
        smart_select,
        sources,
        studio,
        studio_advanced,
    )
    from .tools._utils import register_all_tools

    # Register collected tools with mcp
    register_all_tools(mcp)

    # Optionally hide tool groups/tools via environment variables (opt-in).
    from . import tool_groups

    tool_groups.apply(mcp)


# Register tools on import
_register_tools()


def main() -> None:
    """Run the MCP server.

    Supports multiple transports:
    - stdio (default): For desktop apps like Claude Desktop
    - http: Streamable HTTP for network access
    - sse: Legacy SSE transport (backwards compatibility)
    """
    from notebooklm_tools.utils.io_encoding import configure_stdio_utf8_on_windows

    configure_stdio_utf8_on_windows()

    parser = argparse.ArgumentParser(
        description="Gemini Notebook MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  NOTEBOOKLM_MCP_TRANSPORT     Transport type (stdio, http, sse)
  NOTEBOOKLM_MCP_HOST          Host to bind (default: 127.0.0.1)
  NOTEBOOKLM_MCP_PORT          Port to listen on (default: 8000)
  NOTEBOOKLM_MCP_PATH          MCP endpoint path (default: /mcp)
  NOTEBOOKLM_MCP_STATELESS     Stateless HTTP sessions (default: true, set false to disable)
  NOTEBOOKLM_MCP_DEBUG         Debug logging (default: false)
  NOTEBOOKLM_HL                Interface language and default artifact language (default: en)
  NOTEBOOKLM_QUERY_TIMEOUT     Query timeout in seconds (default: 120.0)

Examples:
  notebooklm-mcp                              # Default stdio transport
  notebooklm-mcp --transport http             # HTTP on localhost:8000
  notebooklm-mcp --transport http --port 3000 # HTTP on custom port
  notebooklm-mcp --debug                      # Enable debug logging
        """,
    )

    parser.add_argument(
        "--transport",
        "-t",
        choices=["stdio", "http", "sse"],
        default=os.environ.get("NOTEBOOKLM_MCP_TRANSPORT", "stdio"),
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        "-H",
        default=os.environ.get("NOTEBOOKLM_MCP_HOST", "127.0.0.1"),
        help="Host to bind for HTTP/SSE (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=int(os.environ.get("NOTEBOOKLM_MCP_PORT", "8000")),
        help="Port for HTTP/SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--path",
        default=os.environ.get("NOTEBOOKLM_MCP_PATH", "/mcp"),
        help="MCP endpoint path for HTTP (default: /mcp)",
    )
    parser.add_argument(
        "--stateless",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("NOTEBOOKLM_MCP_STATELESS", default=True),
        help=(
            "Stateless HTTP sessions (default: true). Avoids MCP SDK double-response crash "
            "(python-sdk#2416). NOTE: this affects the MCP HTTP transport layer only — "
            "it does NOT control the in-process conversation history cache. To bound the "
            "conversation cache (e.g. for long-lived servers), set "
            "NOTEBOOKLM_CONVERSATION_MAX_TURNS / NOTEBOOKLM_CONVERSATION_MAX_CONVS."
        ),
    )
    parser.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=_env_bool("NOTEBOOKLM_MCP_DEBUG"),
        help="Enable debug logging",
    )
    parser.add_argument(
        "--query-timeout",
        type=float,
        default=float(os.environ.get("NOTEBOOKLM_QUERY_TIMEOUT", "120.0")),
        help="Query timeout in seconds (default: 120.0)",
    )

    args = parser.parse_args()

    # Configure debug logging
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        mcp_logger.setLevel(logging.DEBUG)
        # Also enable core client logging
        logging.getLogger("notebooklm_tools.core").setLevel(logging.DEBUG)

    # Set query timeout
    from .tools._utils import set_query_timeout

    set_query_timeout(args.query_timeout)

    # Run server with appropriate transport
    # show_banner=False prevents Rich box-drawing output that can corrupt
    # the JSON-RPC protocol on Windows (especially with non-English locales)
    import sys

    if args.transport == "stdio":

        class _StdoutToStderrWrapper:
            """Redirects sys.stdout.write to sys.stderr, but preserves original buffer.

            This ensures that stray print() statements and logs go to stderr and do not
            corrupt the MCP JSON-RPC protocol on stdout, while allowing the MCP SDK to
            write the JSON-RPC messages to the original stdout buffer.
            """

            def __init__(self, original_stdout):
                self._original_stdout = original_stdout
                self.buffer = getattr(original_stdout, "buffer", original_stdout)

            def write(self, s):
                return sys.stderr.write(s)

            def flush(self):
                sys.stderr.flush()

            def __getattr__(self, name):
                return getattr(self._original_stdout, name)

        sys.stdout = _StdoutToStderrWrapper(sys.stdout)

        mcp.run(show_banner=False)
    elif args.transport in ("http", "sse"):
        _LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
        if args.host not in _LOOPBACK_HOSTS:
            if not _env_bool("NOTEBOOKLM_ALLOW_EXTERNAL_BIND"):
                print(
                    f"SECURITY ERROR: Refusing to bind to non-loopback address '{args.host}'.\n"
                    "There is no built-in authentication — binding externally exposes\n"
                    "your Google cookies to anyone on the network.\n\n"
                    "To override, set: NOTEBOOKLM_ALLOW_EXTERNAL_BIND=1",
                    file=sys.stderr,
                )
                sys.exit(1)
            import warnings

            warnings.warn(
                f"SECURITY WARNING: {args.transport.upper()} transport is bound to a "
                f"non-loopback address ('{args.host}'). There is no built-in "
                "authentication. Do not expose this port to untrusted networks.",
                stacklevel=2,
            )
        if args.transport == "http":
            mcp.run(
                transport="streamable-http",
                host=args.host,
                port=args.port,
                path=args.path,
                stateless_http=args.stateless,
                show_banner=False,
            )
        else:
            mcp.run(
                transport="sse",
                host=args.host,
                port=args.port,
                show_banner=False,
            )


if __name__ == "__main__":
    main()
