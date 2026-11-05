"""Optional MCP plugin loading for third-party NotebookLM extensions.

The core server owns built-in tool registration. This module adds a small,
stable extension seam for optional tools/routes without requiring downstream
integrations to patch ``server.py`` or built-in tool modules.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
from collections.abc import Callable, Sequence
from importlib import metadata
from typing import Any, cast

PLUGIN_ENTRY_POINT_GROUP = "notebooklm_tools.mcp_plugins"
PLUGIN_ENV_VAR = "NOTEBOOKLM_MCP_PLUGINS"
PLUGIN_AUTOLOAD_ENV_VAR = "NOTEBOOKLM_MCP_PLUGIN_AUTOLOAD"
PLUGIN_STRICT_ENV_VAR = "NOTEBOOKLM_MCP_PLUGIN_STRICT"

_FALSY = frozenset({"", "false", "0", "no", "off"})
_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})
logger = logging.getLogger("notebooklm_tools.mcp.plugins")
PluginCallable = Callable[..., Any]
PluginLoadResult = dict[str, str]


class PluginLoadError(RuntimeError):
    """Raised when an explicitly configured plugin cannot be loaded."""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _FALSY:
        return False
    if normalized in _TRUE_VALUES:
        return True
    return default


def _split_plugin_specs(raw: str | None) -> list[str]:
    """Split a comma-separated plugin spec list while ignoring blanks."""
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _entry_points() -> list[metadata.EntryPoint]:
    """Return installed NotebookLM MCP plugin entry points."""
    return list(metadata.entry_points().select(group=PLUGIN_ENTRY_POINT_GROUP))


def _load_entry_point(name: str) -> PluginCallable | None:
    """Load an entry point by name, returning None when absent."""
    for entry_point in _entry_points():
        if entry_point.name == name:
            loaded = entry_point.load()
            return _coerce_plugin_callable(loaded, name)
    return None


def _coerce_plugin_callable(obj: Any, spec: str) -> PluginCallable:
    """Normalize a plugin object/module into a callable registration function."""
    if callable(obj):
        return cast(PluginCallable, obj)
    register = getattr(obj, "register", None)
    if callable(register):
        return cast(PluginCallable, register)
    raise PluginLoadError(
        f"Plugin '{spec}' must be callable or expose a callable register(mcp) function."
    )


def _load_module_plugin(spec: str) -> PluginCallable:
    """Load a plugin from module or module:attribute syntax."""
    if ":" in spec:
        module_name, attr_name = spec.split(":", 1)
        module_name = module_name.strip()
        attr_name = attr_name.strip()
        if not module_name or not attr_name:
            raise PluginLoadError(f"Invalid plugin spec '{spec}'. Expected module:attribute.")
        module = importlib.import_module(module_name)
        try:
            return _coerce_plugin_callable(getattr(module, attr_name), spec)
        except AttributeError as exc:
            raise PluginLoadError(
                f"Plugin attribute '{attr_name}' not found in {module_name}."
            ) from exc

    entry_point = _load_entry_point(spec)
    if entry_point is not None:
        return entry_point

    module = importlib.import_module(spec)
    return _coerce_plugin_callable(module, spec)


def _invoke_plugin(plugin: PluginCallable, mcp: Any) -> Any:
    """Invoke a plugin callable with the FastMCP instance when it accepts one."""
    try:
        signature = inspect.signature(plugin)
    except (TypeError, ValueError):
        return plugin(mcp)

    required_positional = [
        param
        for param in signature.parameters.values()
        if param.default is inspect.Parameter.empty
        and param.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    accepts_variadic = any(
        param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values()
    )
    accepts_keyword_mcp = any(
        param.name == "mcp"
        and param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        for param in signature.parameters.values()
    )

    if accepts_keyword_mcp and not required_positional:
        return plugin(mcp=mcp)
    if required_positional or accepts_variadic:
        return plugin(mcp)
    return plugin()


def _configured_plugin_specs() -> list[str]:
    specs = _split_plugin_specs(os.environ.get(PLUGIN_ENV_VAR))
    if specs:
        return specs
    if _env_bool(PLUGIN_AUTOLOAD_ENV_VAR):
        return [entry_point.name for entry_point in _entry_points()]
    return []


def load_plugins(
    mcp: Any,
    plugin_specs: Sequence[str] | None = None,
    *,
    strict: bool | None = None,
) -> list[PluginLoadResult]:
    """Load and register optional MCP plugins.

    Plugins are disabled by default. Configure explicit plugins with
    ``NOTEBOOKLM_MCP_PLUGINS`` as a comma-separated list. Each item can be:

    - an entry point name from ``notebooklm_tools.mcp_plugins``;
    - a Python module exposing ``register(mcp)``;
    - ``module:function`` pointing at a callable.

    Set ``NOTEBOOKLM_MCP_PLUGIN_AUTOLOAD=true`` to load all installed entry
    points from the group. Explicit plugin failures are fatal by default;
    set ``NOTEBOOKLM_MCP_PLUGIN_STRICT=false`` to log failures and continue.
    """
    specs = list(plugin_specs) if plugin_specs is not None else _configured_plugin_specs()
    if not specs:
        return []

    strict_mode = _env_bool(PLUGIN_STRICT_ENV_VAR, default=True) if strict is None else strict
    results: list[PluginLoadResult] = []

    for spec in specs:
        try:
            plugin = _load_module_plugin(spec)
            _invoke_plugin(plugin, mcp)
            results.append({"name": spec, "status": "loaded"})
            logger.info("Loaded NotebookLM MCP plugin: %s", spec)
        except Exception as exc:
            message = f"Failed to load NotebookLM MCP plugin '{spec}': {exc}"
            if strict_mode:
                raise PluginLoadError(message) from exc
            logger.exception(message)
            results.append({"name": spec, "status": "error", "error": str(exc)})

    return results
