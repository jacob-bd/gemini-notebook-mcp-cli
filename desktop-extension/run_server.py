#!/usr/bin/env python3
"""Robust launcher for NotebookLM MCP Server in Claude Desktop.

Claude Desktop on macOS runs with a restricted PATH, so `uvx` may not be
discoverable. This script searches common install locations before falling back
to the system PATH.

Bundled inside the .mcpb extension and invoked via manifest.json:
    "command": "python3", "args": ["${__dirname}/run_server.py"]
"""

import glob
import os
import platform
import shutil
import subprocess
import sys


def _find_uvx() -> str | None:
    """Find the uvx executable, checking common locations first."""
    # 1. Try the system PATH (works if user has uvx in PATH)
    found = shutil.which("uvx")
    if found:
        return found

    # 2. Check common install locations per platform
    home = os.path.expanduser("~")
    candidates: list[str] = []

    if platform.system() == "Darwin":  # macOS
        candidates = [
            os.path.join(home, ".local", "bin", "uvx"),
            os.path.join(home, ".cargo", "bin", "uvx"),
            "/opt/homebrew/bin/uvx",
            "/usr/local/bin/uvx",
        ]
    elif platform.system() == "Linux":
        candidates = [
            os.path.join(home, ".local", "bin", "uvx"),
            os.path.join(home, ".cargo", "bin", "uvx"),
            "/usr/local/bin/uvx",
            "/snap/bin/uvx",
        ]
    elif platform.system() == "Windows":
        appdata = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        roaming = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        candidates = [
            os.path.join(home, ".local", "bin", "uvx.exe"),
            os.path.join(home, ".cargo", "bin", "uvx.exe"),
            os.path.join(appdata, "uv", "uvx.exe"),
            os.path.join(home, "scoop", "shims", "uvx.exe"),
        ]
        # `pip install --user uv` places uvx.exe in
        # %APPDATA%\Python\Python3XX\Scripts, which Windows does not add to PATH
        # automatically, so shutil.which() above misses it. Include the Scripts
        # directory of every installed CPython version.
        candidates += sorted(
            glob.glob(os.path.join(roaming, "Python", "Python*", "Scripts", "uvx.exe"))
        )

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    return None


def main() -> None:
    """Find uvx and launch the NotebookLM MCP server."""
    uvx = _find_uvx()

    if not uvx:
        print(
            "Error: Could not find 'uvx'. Please install it first:\n"
            "  curl -LsSf https://astral.sh/uv/install.sh | sh\n"
            "\n"
            "Then restart Claude Desktop.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Run the MCP server — explicit stdio passthrough is critical because
    # Claude Desktop communicates with MCP servers via stdin/stdout JSON-RPC.
    cmd = [uvx, "--from", "notebooklm-mcp-cli", "notebooklm-mcp", *sys.argv[1:]]
    try:
        result = subprocess.run(
            cmd,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            check=False,
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
