"""API client access for the wrapper layers.

`cli/` and `mcp/` build authenticated clients, but must not import from
`core/` directly (see AGENTS.md). This module is the single entry point for
the client class; the lookup resolves lazily so monkeypatching
`core.client.NotebookLMClient` in tests keeps working.
"""

from __future__ import annotations

__all__ = ["NotebookLMClient"]  # noqa: F822 - provided lazily via __getattr__


def __getattr__(name: str):
    """PEP 562 lazy re-export of `core.client.NotebookLMClient`."""
    if name == "NotebookLMClient":
        from notebooklm_tools.core.client import NotebookLMClient

        return NotebookLMClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
