"""Notice state service.

Re-exports the notice and protect-prompt helpers from `core.notices` so
`cli/` and `mcp/` reach them through `services/` (see AGENTS.md). The real
implementation stays in core; lookups resolve lazily so monkeypatching
`core.notices` keeps working.
"""

from __future__ import annotations

_CORE_NOTICE_NAMES = frozenset(
    {
        "cache_probe_result",
        "get_cached_probe_result",
        "get_protect_answer",
        "is_cli_notice_shown",
        "is_mcp_notice_shown",
        "load_notices",
        "mark_cli_notice_shown",
        "mark_mcp_notice_shown",
        "record_protect_answer",
        "save_notices",
    }
)

__all__ = sorted(_CORE_NOTICE_NAMES)


def __getattr__(name: str):
    """PEP 562 lazy re-export of notice helpers from `core.notices`."""
    if name in _CORE_NOTICE_NAMES:
        from notebooklm_tools.core import notices as _core_notices

        return getattr(_core_notices, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
