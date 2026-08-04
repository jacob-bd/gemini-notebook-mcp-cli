"""NotebookLM Tools - Unified CLI and MCP server for Google NotebookLM."""

from __future__ import annotations

from typing import Any

import notebooklm_tools.utils.env_sanitize as _env_sanitize  # noqa: F401

__version__ = "0.9.6"

__all__ = ["NotebookLMClient", "__version__"]


def __getattr__(name: str) -> Any:
    """Lazy-load heavy client so early imports (e.g. stdio encoding) stay light."""
    if name == "NotebookLMClient":
        from notebooklm_tools.core.client import NotebookLMClient as _NotebookLMClient

        globals()["NotebookLMClient"] = _NotebookLMClient
        return _NotebookLMClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
