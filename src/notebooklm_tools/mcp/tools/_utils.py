"""MCP Tools - Shared utilities and base components."""

import functools
import inspect
import json
import logging
import os
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeAlias, TypeVar, cast

from notebooklm_tools.services.auth import extract_cookies_from_chrome_export, load_cached_tokens
from notebooklm_tools.services.client import NotebookLMClient
from notebooklm_tools.services.errors import ServiceError

# MCP request/response logger
mcp_logger = logging.getLogger("notebooklm_tools.mcp")

# Keys that must never appear in log output, matched exactly.
_SENSITIVE_PARAMS = frozenset(
    {"cookies", "csrf_token", "session_id", "request_body", "request_url"}
)

# Substrings that mark a key as sensitive wherever it appears, including in
# nested response payloads. An exact denylist is fail-open: any key added to a
# tool signature or a service return value later would log in clear by default.
# These markers make the common shapes fail closed instead.
_SENSITIVE_MARKERS = (
    "cookie",
    "csrf",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "apikey",
    "api_key",
    "authorization",
    "bearer",
    "session_id",
    "sessionid",
    "request_body",
    "request_url",
)

# Guard against deeply nested or self-referential payloads.
_MAX_REDACT_DEPTH = 8
P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")
ResultDict: TypeAlias = dict[str, Any]
_StrConverter: TypeAlias = Callable[[Any], str]
_DEFAULT_STR_CONVERTER: _StrConverter = str


def _is_sensitive_key(key: str) -> bool:
    """True if a key name should have its value redacted before logging."""
    if key in _SENSITIVE_PARAMS:
        return True
    normalized = key.lower()
    return any(marker in normalized for marker in _SENSITIVE_MARKERS)


def _redact(value: Any, _depth: int = 0) -> Any:
    """Recursively replace sensitive values with [REDACTED] before logging.

    Walks dicts and lists so nested payloads are covered, not just top-level
    keyword arguments.
    """
    if _depth >= _MAX_REDACT_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            k: "[REDACTED]"
            if isinstance(k, str) and _is_sensitive_key(k)
            else _redact(v, _depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, _depth + 1) for item in value]
    return value


def _sanitize_params(params: ResultDict) -> ResultDict:
    """Replace sensitive parameter values with [REDACTED] before logging."""
    return cast(ResultDict, _redact(params))


def error_result(
    error: str,
    *,
    hint: str | None = None,
    status: str = "error",
    **extra: Any,
) -> ResultDict:
    """Build a consistent error payload for MCP tools."""
    result: ResultDict = {"status": status, "error": error}
    if hint:
        result["hint"] = hint
    result.update(extra)
    return result


def service_error_result(error: ServiceError, *, status: str = "error") -> ResultDict:
    """Serialize a ServiceError without breaking the existing MCP error shape."""
    result = error_result(error.user_message, hint=error.hint, status=status)
    details = error.details()
    if details:
        result["error_details"] = details
    return result


# Global state
_client: NotebookLMClient | None = None
_client_lock = threading.Lock()
_query_timeout: float = float(os.environ.get("NOTEBOOKLM_QUERY_TIMEOUT", "120.0"))
_mcp_probe_event = threading.Event()
_mcp_probe_available = False
_mcp_probe_thread: threading.Thread | None = None
_allow_mcp_bg_probe: bool = False


def reset_mcp_probe_state(timeout: float = 2.0) -> None:
    """Reset the MCP background probe state and join any running probe thread."""
    global _mcp_probe_available, _mcp_probe_thread
    if _mcp_probe_thread is not None and _mcp_probe_thread.is_alive():
        _mcp_probe_thread.join(timeout=timeout)
    _mcp_probe_thread = None
    _mcp_probe_available = False
    _mcp_probe_event.clear()


def start_mcp_background_probe(
    storage_dir: Path | None = None,
    backend_factory: Callable[[], Any] | None = None,
    *,
    force: bool = False,
) -> None:
    """Start background probe thread once at MCP server start.

    Captures target storage directory and backend factory at thread launch time
    to prevent thread from resolving dynamically during test environment teardown.
    """
    global _mcp_probe_thread
    if not force and os.environ.get("PYTEST_CURRENT_TEST") and not _allow_mcp_bg_probe:
        return

    if _mcp_probe_thread is not None and _mcp_probe_thread.is_alive():
        _mcp_probe_thread.join(timeout=2.0)

    _mcp_probe_event.clear()

    from notebooklm_tools.services.auth_storage import CredentialStore, get_backend_factory
    from notebooklm_tools.utils.config import get_storage_dir

    captured_storage_dir = storage_dir if storage_dir is not None else get_storage_dir()
    captured_factory = backend_factory if backend_factory is not None else get_backend_factory()

    def _worker(target_dir: Path, factory: Callable[[], Any]) -> None:
        global _mcp_probe_available
        try:
            from notebooklm_tools.services.notices import is_mcp_notice_shown

            if is_mcp_notice_shown(storage_dir=target_dir):
                _mcp_probe_available = False
                return

            from notebooklm_tools.services.auth import AuthManager
            from notebooklm_tools.utils.config import get_auth_storage_mode, get_config

            profile = get_config().auth.default_profile
            if not AuthManager(profile).profile_exists():
                _mcp_probe_available = False
                return

            if get_auth_storage_mode(profile) != "file":
                _mcp_probe_available = False
                return

            backend = factory() if factory is not None else None
            store = CredentialStore(storage_dir=target_dir, backend=backend)
            _mcp_probe_available = store.should_offer_protection(profile_name=profile)
        except Exception:
            _mcp_probe_available = False
        finally:
            _mcp_probe_event.set()

    _mcp_probe_thread = threading.Thread(
        target=_worker,
        args=(captured_storage_dir, captured_factory),
        name="nlm-mcp-bg-probe",
        daemon=True,
    )
    _mcp_probe_thread.start()


def maybe_attach_mcp_notice(result: Any) -> None:
    """Attach one-time notice to tool response if background probe has completed and succeeded.

    Never probes inside tool calls. If background thread hasn't finished, does not attach notice.
    """
    if not isinstance(result, dict):
        return
    if not _mcp_probe_event.is_set() or not _mcp_probe_available:
        return
    from notebooklm_tools.services.notices import (
        get_protect_answer,
        is_mcp_notice_shown,
        mark_mcp_notice_shown,
    )

    # The probe looked at the profile active at server start; re-check the one active now
    # (a profile switch may have moved us to a protected or already-answered profile).
    try:
        from notebooklm_tools.utils.config import get_auth_storage_mode, get_config

        active = get_config().auth.default_profile
        if get_auth_storage_mode(active) != "file" or get_protect_answer(active) is not None:
            return
    except Exception:
        return

    if is_mcp_notice_shown():
        return

    result["user_notice"] = (
        "Tell the user once, in one short line: their saved Gemini Notebook login can "
        "optionally be protected in the OS keystore by running "
        "'nlm auth storage set protected'. Don't repeat this."
    )
    mark_mcp_notice_shown()


def maybe_attach_active_profile_note(result: Any, tool_name: str) -> None:
    """Say which account is in use while a session profile switch is active.

    Only when several profiles are saved: with one profile a switch is meaningless, and
    on the saved default there is nothing surprising to report. The server may be shared
    by several chats, so every result carries the note until the switch is cleared.
    """
    if not isinstance(result, dict) or tool_name == "profile":
        return
    try:
        from notebooklm_tools.services.auth_storage import saved_profile_names
        from notebooklm_tools.utils.config import (
            get_config,
            get_saved_default_profile,
            get_session_profile,
        )

        if not get_session_profile() or len(saved_profile_names()) < 2:
            return
        active = get_config().auth.default_profile
        result["active_profile_note"] = (
            f"Using profile '{active}' because of a session switch (saved default: "
            f"'{get_saved_default_profile()}'). If the user has not been told which account "
            "this is in this conversation, tell them."
        )
    except Exception:
        return


def get_query_timeout() -> float:
    """Get the query timeout value."""
    return _query_timeout


def set_query_timeout(timeout: float) -> None:
    """Set the query timeout value."""
    global _query_timeout
    _query_timeout = timeout


def get_client() -> NotebookLMClient:
    """Get or create the API client (thread-safe).

    Tries environment variables first, falls back to cached tokens from auth CLI.
    Keystore reads are performed outside _client_lock to avoid blocking unrelated
    MCP operations while keeping the hot path sub-millisecond.
    """
    global _client

    cookie_header = os.environ.get("NOTEBOOKLM_COOKIES", "")
    if cookie_header:
        with _client_lock:
            if _client is not None and getattr(_client, "_is_env_auth", False):
                return _client
            cookies = extract_cookies_from_chrome_export(cookie_header)
            _client = NotebookLMClient(
                cookies=cookies,
                csrf_token="",
                session_id="",
                build_label="",
                base_host="",
                is_env_auth=True,
            )
            return _client

    # Profile-based authentication
    from notebooklm_tools.services.auth_storage import get_envelope_revision
    from notebooklm_tools.utils.config import (
        get_auth_storage_mode,
        get_config,
        get_profile_dir,
        reset_config,
    )

    with _client_lock:
        reset_config()
        default_profile = get_config().auth.default_profile
        mode = get_auth_storage_mode(default_profile)

        if (
            _client is not None
            and not getattr(_client, "_is_env_auth", False)
            and getattr(_client, "_profile_name", None) == default_profile
        ):
            if mode == "protected":
                enc_path = get_profile_dir(default_profile, create=False) / "credentials.enc"
                if enc_path.exists():
                    current_rev = get_envelope_revision(enc_path)
                    if current_rev is not None and current_rev == getattr(
                        _client, "_auth_revision", None
                    ):
                        # Fast hot path: <0.05 ms, 0 spawns
                        return _client
            else:
                # File mode parity with main: keep existing _client if reload fails or returns None
                try:
                    cached = load_cached_tokens(default_profile)
                    if cached:
                        cookies_changed = getattr(_client, "cookies", None) != cached.cookies
                        disk_is_newer = cached.extracted_at > getattr(_client, "_created_at", 0)
                        if cookies_changed or disk_is_newer:
                            _client = None
                except Exception:
                    pass

                if _client is not None:
                    return _client

    # Keystore work OUTSIDE _client_lock
    cached = load_cached_tokens(default_profile)
    if not cached:
        raise ValueError(
            "No authentication found. Either:\n"
            "1. Run 'nlm login' to authenticate via Chrome, or\n"
            "2. Set NOTEBOOKLM_COOKIES environment variable manually"
        )

    new_client = NotebookLMClient(
        cookies=cached.cookies,
        csrf_token=cached.csrf_token,
        session_id=cached.session_id,
        build_label=cached.build_label or "",
        base_host=cached.base_host or "",
        profile_name=default_profile,
        auth_revision=cached.revision,
        is_env_auth=False,
    )

    with _client_lock:
        # Compare-and-install
        if (
            _client is not None
            and not getattr(_client, "_is_env_auth", False)
            and getattr(_client, "_profile_name", None) == default_profile
        ):
            if mode == "protected":
                if getattr(_client, "_auth_revision", None) == cached.revision:
                    return _client
            else:
                if not (
                    getattr(_client, "cookies", None) != cached.cookies
                    or cached.extracted_at > getattr(_client, "_created_at", 0)
                ):
                    return _client
        _client = new_client
        return _client


def reset_client() -> None:
    """Reset the client to force re-initialization."""
    global _client
    with _client_lock:
        _client = None


def get_mcp_instance() -> Any:
    """Get the FastMCP instance. Import here to avoid circular imports."""
    from notebooklm_tools.mcp.server import mcp

    return mcp


# Registry for tools - allows registration without immediate mcp dependency
_tool_registry: list[tuple[str, Callable[..., Any]]] = []


def _resolve_notebook_alias(
    sig: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Swap a notebook alias for its real ID (keyword or positional); others pass through."""
    if "notebook_id" not in sig.parameters:
        return args, kwargs
    bound = sig.bind_partial(*args, **kwargs)
    value = bound.arguments.get("notebook_id")
    if isinstance(value, str) and value:
        from notebooklm_tools.services.aliases import resolve

        bound.arguments["notebook_id"] = resolve(value)
    return bound.args, bound.kwargs


def unlogged_tool() -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Register a privacy-sensitive MCP tool without serializing its arguments/results.

    This retains the normal central registry and tool-group gating behavior.
    Use only for operations whose queries or returned contents must not appear
    in debug MCP logs. Errors must still be sanitized by the tool itself.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        sig = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            args, kwargs = _resolve_notebook_alias(sig, args, kwargs)
            result = func(*args, **kwargs)
            maybe_attach_mcp_notice(result)
            maybe_attach_active_profile_note(result, func.__name__)
            return result

        _tool_registry.append((func.__name__, cast(Callable[..., Any], wrapper)))
        return wrapper

    return decorator


def logged_tool() -> Callable[[Callable[P, Any]], Callable[P, Any]]:
    """Decorator that adds MCP request/response logging to a tool.

    Decorated tools are added to the internal registry for later MCP server
    registration via ``register_all_tools()`` rather than being registered
    immediately when decorated. Supports both synchronous and asynchronous
    functions.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        is_async = inspect.iscoroutinefunction(func)
        sig = inspect.signature(func)

        if is_async:
            async_func = cast(Callable[P, Awaitable[Any]], func)

            @functools.wraps(async_func)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                args, kwargs = _resolve_notebook_alias(sig, args, kwargs)
                tool_name = async_func.__name__
                if mcp_logger.isEnabledFor(logging.DEBUG):
                    params = _sanitize_params({k: v for k, v in kwargs.items() if v is not None})
                    mcp_logger.debug(f"MCP Request: {tool_name}({json.dumps(params, default=str)})")

                result: Any = await async_func(*args, **kwargs)
                maybe_attach_mcp_notice(result)
                maybe_attach_active_profile_note(result, tool_name)

                if mcp_logger.isEnabledFor(logging.DEBUG):
                    result_str = json.dumps(_redact(result), default=str)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "..."
                    mcp_logger.debug(f"MCP Response: {tool_name} -> {result_str}")

                return result

            wrapper = cast(Callable[P, R], async_wrapper)
        else:
            sync_func = func

            @functools.wraps(sync_func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                args, kwargs = _resolve_notebook_alias(sig, args, kwargs)
                tool_name = sync_func.__name__
                if mcp_logger.isEnabledFor(logging.DEBUG):
                    params = _sanitize_params({k: v for k, v in kwargs.items() if v is not None})
                    mcp_logger.debug(f"MCP Request: {tool_name}({json.dumps(params, default=str)})")

                result: R = sync_func(*args, **kwargs)
                maybe_attach_mcp_notice(result)
                maybe_attach_active_profile_note(result, tool_name)

                if mcp_logger.isEnabledFor(logging.DEBUG):
                    result_str = json.dumps(_redact(result), default=str)
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "..."
                    mcp_logger.debug(f"MCP Response: {tool_name} -> {result_str}")

                return result

            wrapper = sync_wrapper

        # Store for later registration
        _tool_registry.append((func.__name__, cast(Callable[..., Any], wrapper)))
        return wrapper

    return decorator


def register_all_tools(mcp: Any) -> None:
    """Register all collected tools with the MCP instance."""
    for _, wrapper in _tool_registry:
        mcp.tool()(wrapper)


# Essential cookies for NotebookLM API authentication
ESSENTIAL_COOKIES = [
    "SID",
    "HSID",
    "SSID",
    "APISID",
    "SAPISID",  # Core auth cookies
    "__Secure-1PSID",
    "__Secure-3PSID",  # Secure session variants
    "__Secure-1PAPISID",
    "__Secure-3PAPISID",  # Secure API variants
    "OSID",
    "__Secure-OSID",  # Origin-bound session
    "__Secure-1PSIDTS",
    "__Secure-3PSIDTS",  # Timestamp tokens (rotate frequently)
    "SIDCC",
    "__Secure-1PSIDCC",
    "__Secure-3PSIDCC",  # Session cookies (rotate frequently)
]


def coerce_list(
    val: object | None,
    item_type: Callable[[Any], T] = _DEFAULT_STR_CONVERTER,
) -> list[T] | None:
    """Coerce a value into a list of ``item_type``.

    MCP clients (Claude Desktop, Cursor, etc.) may serialize list parameters as:
      - An actual Python list  → pass through
      - A JSON string          → ``'["a","b"]'``
      - A comma-separated str  → ``'a,b,c'``
      - A single bare value    → ``'a'``
      - A serialized JSON null → ``None``
      - A null string-list sentinel → ``None``
      - None                   → ``None``

    This helper normalizes all forms into ``list[item_type]`` while preserving
    ``None`` as ``None`` for "use default / all" semantics.
    """
    converter = item_type
    if val is None:
        return None  # Preserve None semantics (means "use default / all")
    if isinstance(val, list):
        if converter is _DEFAULT_STR_CONVERTER and val == ["null"]:
            return None
        return [converter(x) for x in val]
    if isinstance(val, str):
        val = val.strip()
        if not val or val == "null":
            return None
        if val.startswith("["):
            try:
                parsed = json.loads(val)
                if converter is _DEFAULT_STR_CONVERTER and parsed == ["null"]:
                    return None
                return [converter(x) for x in parsed]
            except (json.JSONDecodeError, ValueError):
                pass  # Fall through to comma-split
        return [converter(x.strip()) for x in val.split(",") if x.strip()]
    # Single non-string value (e.g. an int)
    return [converter(val)]
