"""Chrome DevTools Protocol (CDP) utilities for cookie extraction.

This module provides a keychain-free way to extract cookies from Chrome
by using the Chrome DevTools Protocol over WebSocket.

Usage:
    1. Chrome is launched with --remote-debugging-port
    2. We connect via WebSocket and use Network.getCookies
    3. No keychain access required!
"""

import contextlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from httpx import Client, HTTPTransport

# Disable proxy for localhost CDP connections — system proxies (Surge, Clash, etc.)
# can intercept localhost requests and break Chrome DevTools Protocol connections.
# See: https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/119
httpx_client = Client(
    trust_env=False,
    mounts={
        "http://": HTTPTransport(proxy=None),
        "https://": HTTPTransport(proxy=None),
    },
)
import websocket  # noqa: E402

_cached_ws: websocket.WebSocket | None = None
_cached_ws_url: str | None = None
_cdp_ws_lock = threading.Lock()
_cdp_next_command_id = 0


def _next_cdp_command_id() -> int:
    """Return a process-local monotonically increasing CDP command id."""
    global _cdp_next_command_id
    _cdp_next_command_id += 1
    return _cdp_next_command_id


def _reset_cached_ws_unlocked() -> None:
    """Close and clear the cached CDP websocket. Caller must hold _cdp_ws_lock."""
    global _cached_ws, _cached_ws_url
    if _cached_ws is not None:
        with contextlib.suppress(Exception):
            _cached_ws.close()
    _cached_ws = None
    _cached_ws_url = None


def _normalize_ws_url(url: str | None) -> str | None:
    """Normalize WebSocket URLs to use 127.0.0.1 instead of localhost.

    On Windows, Chrome's debugger binds to IPv4 only, but
    websocket-client may resolve 'localhost' to ::1 (IPv6),
    causing WinError 10013.  Using the explicit IPv4 loopback
    address avoids the ambiguity on all platforms.

    See: https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/108
    """
    if url and "://localhost:" in url:
        url = url.replace("://localhost:", "://127.0.0.1:")
    return url


from notebooklm_tools.core.exceptions import AuthenticationError  # noqa: E402
from notebooklm_tools.utils.config import (  # noqa: E402
    get_base_url,
    get_enterprise_location,
    get_enterprise_project_id,
    get_home_dir,
)

__all__ = [
    "get_chrome_path",
    "get_browser_display_name",
    "get_supported_browsers",
    "extract_cookies_via_cdp",
    "extract_cookies_via_existing_cdp",
    "close_profile_owned_cdp_browser",
    "run_headless_auth",
    "has_chrome_profile",
    "terminate_chrome",
]

CDP_DEFAULT_PORT = 9222
CDP_PORT_RANGE = range(9222, 9232)  # Ports to scan for existing/available


def get_notebooklm_url() -> str:
    """Return the browser URL used to authenticate the configured account."""
    base_url = get_base_url()
    host = (urlparse(base_url).hostname or "").lower()
    enterprise_hosts = {
        "notebooklm.cloud.google.com",
        "notebook.cloud.google.com",
        "vertexaisearch.cloud.google.com",
    }
    if host not in enterprise_hosts:
        return f"{base_url}/"

    project_id = get_enterprise_project_id()
    if not project_id:
        raise ValueError(
            "NOTEBOOKLM_PROJECT_ID is required when authenticating Gemini Notebook Enterprise."
        )
    location = get_enterprise_location()
    prefix = (
        f"/notebooklm/{location}" if host == "vertexaisearch.cloud.google.com" else f"/{location}"
    )
    return f"{base_url}{prefix}/?project={quote(project_id, safe='')}"


NOTEBOOKLM_URL = get_notebooklm_url()

import logging as _logging  # noqa: E402

_logger = _logging.getLogger(__name__)


def _cdp_http_base(port: int) -> str:
    """Return the local CDP HTTP base URL using IPv4 loopback explicitly."""
    return f"http://127.0.0.1:{port}"


_STARTUP_STDERR_TAIL_BYTES = 65536


def _close_process_streams(process: subprocess.Popen | None) -> None:
    """Close any stdio pipes or temporary stderr capture file attached to a process."""
    if process is None:
        return
    for attr in ("stdout", "stderr", "_nlm_stderr_file"):
        stream = getattr(process, attr, None)
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()
            if attr == "_nlm_stderr_file":
                with contextlib.suppress(Exception):
                    process._nlm_stderr_file = None  # type: ignore[attr-defined]


def _summarize_browser_startup_failure(process: subprocess.Popen | None) -> str | None:
    """Best-effort summary when the launched browser exits before CDP is ready."""
    if process is None or process.poll() is None:
        return None

    exit_code = process.poll()
    stderr_file = getattr(process, "_nlm_stderr_file", None)
    if stderr_file is None and process.stderr is None:
        return f"Process exited with code {exit_code}"

    try:
        if stderr_file is not None:
            stderr_file.seek(0, os.SEEK_END)
            size = stderr_file.tell()
            stderr_file.seek(max(0, size - _STARTUP_STDERR_TAIL_BYTES))
            raw_stderr = stderr_file.read()
        else:
            raw_stderr = process.stderr.read()
        stderr = raw_stderr.decode("utf-8", errors="replace").strip()
    except Exception:
        return f"Process exited with code {exit_code}"
    finally:
        if stderr_file is not None:
            _close_process_streams(process)

    if not stderr:
        return f"Process exited with code {exit_code}"

    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return f"Process exited with code {exit_code}"

    return f"Exit code {exit_code}: {lines[-1]}"


# =============================================================================
# Port-to-Profile Mapping
# =============================================================================
# Tracks which CDP port belongs to which NLM profile so we never reuse
# a Chrome instance from a different profile.


def _get_port_map_file() -> Path:
    """Get path to chrome-port-map.json."""
    from notebooklm_tools.utils.config import get_storage_dir

    return get_storage_dir() / "chrome-port-map.json"


def _pid_is_alive(pid: int) -> bool:
    """Return whether a process is still running on the current platform."""
    if platform.system() != "Windows":
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _read_port_map() -> dict[str, dict]:
    """Read the port map, pruning entries whose PIDs are no longer alive.

    Returns:
        Dict mapping port (as string key) to {"profile": str, "pid": int}.
    """
    map_file = _get_port_map_file()
    if not map_file.exists():
        return {}

    try:
        data = json.loads(map_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    # Prune stale entries (dead PIDs)
    alive: dict[str, dict] = {}
    changed = False
    for port_str, entry in data.items():
        pid = entry.get("pid")
        if pid is not None:
            if _pid_is_alive(pid):
                alive[port_str] = entry
            else:
                changed = True  # PID is dead, skip it
        else:
            alive[port_str] = entry

    if changed:
        _save_port_map(alive)

    return alive


def _save_port_map(data: dict[str, dict]) -> None:
    """Write port map to disk with restrictive permissions from creation."""
    map_file = _get_port_map_file()
    try:
        fd = os.open(str(map_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise
        with f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # Best-effort


def _write_port_map(port: int, profile_name: str, pid: int) -> None:
    """Record which profile owns which port."""
    data = _read_port_map()
    data[str(port)] = {"profile": profile_name, "pid": pid}
    _save_port_map(data)


def _clear_port_map(port: int) -> None:
    """Remove a port entry after Chrome terminates."""
    data = _read_port_map()
    if str(port) in data:
        del data[str(port)]
        _save_port_map(data)


def normalize_cdp_http_url(cdp_url: str) -> str:
    """Normalize a CDP endpoint into an HTTP base URL.

    Accepts:
      - http://127.0.0.1:18800
      - ws://127.0.0.1:18800/devtools/browser/<id>
      - 127.0.0.1:18800
      - 18800
    """
    raw = (cdp_url or "").strip()
    if not raw:
        raise ValueError("cdp_url is required")

    # Bare port shorthand
    if raw.isdigit():
        return f"http://127.0.0.1:{raw}"

    if raw.startswith(("ws://", "wss://")):
        parsed = urlparse(raw)
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"Invalid CDP websocket URL: {cdp_url}")
        scheme = "https" if parsed.scheme == "wss" else "http"
        return f"{scheme}://{parsed.hostname}:{parsed.port}"

    if raw.startswith(("http://", "https://")):
        return raw.rstrip("/")

    # host:port
    return f"http://{raw.rstrip('/')}"


def find_available_port(
    starting_from: int = 9222,
    max_attempts: int = 10,
    *,
    allow_ephemeral_fallback: bool = True,
) -> int:
    """Find an available loopback port for Chrome debugging.

    Scans the conventional CDP range first. If every candidate is unavailable,
    optionally asks the OS for an ephemeral loopback port. The fallback matters
    on Windows hosts where Hyper-V/WinNAT can reserve a large contiguous block
    around 9222 even when no process is listening there.

    Args:
        starting_from: Port to start scanning from.
        max_attempts: Number of adjacent ports to try first.
        allow_ephemeral_fallback: If True, use an OS-assigned loopback port when
            the requested range is unavailable. Exact-port callers can disable
            this and retain the historical RuntimeError behavior.

    Returns:
        An available port number.

    Raises:
        RuntimeError: If no available port can be reserved.
    """
    import socket

    for offset in range(max_attempts):
        port = starting_from + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue

    if allow_ephemeral_fallback:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", 0))
                return int(s.getsockname()[1])
        except OSError:
            pass

    raise RuntimeError(
        f"No available ports in range {starting_from}-{starting_from + max_attempts - 1}. "
        "Close some applications and try again."
    )


# ---------------------------------------------------------------------------
# Browser candidate tables — (display_name, path_or_executable) tuples.
# Ordered by preference: Google Chrome first, then popular Chromium forks.
# The display_name is used in error messages so it always stays in sync with
# what we actually search for.
# ---------------------------------------------------------------------------


# macOS: absolute .app bundle paths, /Applications first then ~/Applications
def _macos_browser_candidates() -> list[tuple[str, str]]:
    home_apps = get_home_dir() / "Applications"
    entries: list[tuple[str, str]] = [
        ("Google Chrome", "Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("Arc", "Arc.app/Contents/MacOS/Arc"),
        ("Dia", "Dia.app/Contents/MacOS/Dia"),
        ("Comet", "Comet.app/Contents/MacOS/Comet"),
        ("Brave Browser", "Brave Browser.app/Contents/MacOS/Brave Browser"),
        ("Microsoft Edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("Microsoft Edge Beta", "Microsoft Edge Beta.app/Contents/MacOS/Microsoft Edge Beta"),
        ("Chromium", "Chromium.app/Contents/MacOS/Chromium"),
        ("Vivaldi", "Vivaldi.app/Contents/MacOS/Vivaldi"),
        ("Opera", "Opera.app/Contents/MacOS/Opera"),
        ("Opera GX", "Opera GX.app/Contents/MacOS/Opera GX"),
    ]
    candidates: list[tuple[str, str]] = []
    for name, rel in entries:
        candidates.append((name, str(Path("/Applications") / rel)))
        candidates.append((name, str(home_apps / rel)))
    return candidates


# Linux: `shutil.which`-able executable names
_LINUX_BROWSER_CANDIDATES: list[tuple[str, str]] = [
    ("Google Chrome", "google-chrome"),
    ("Google Chrome", "google-chrome-stable"),
    ("Chromium", "chromium"),
    ("Chromium", "chromium-browser"),
    ("Brave Browser", "brave-browser"),
    ("Microsoft Edge", "microsoft-edge-stable"),
    ("Microsoft Edge", "microsoft-edge"),
    ("Microsoft Edge Beta", "microsoft-edge-beta"),
    ("Vivaldi", "vivaldi-stable"),
    ("Vivaldi", "vivaldi"),
    ("Opera", "opera"),
]


# Windows: absolute paths.  User-local installs live under %LOCALAPPDATA%.
def _windows_browser_candidates() -> list[tuple[str, str]]:
    home_dir = get_home_dir()
    local = home_dir / "AppData" / "Local"
    roaming = home_dir / "AppData" / "Roaming"
    pf = Path(r"C:\Program Files")
    pf86 = Path(r"C:\Program Files (x86)")
    return [
        ("Google Chrome", str(pf / r"Google\Chrome\Application\chrome.exe")),
        ("Google Chrome", str(pf86 / r"Google\Chrome\Application\chrome.exe")),
        ("Google Chrome", str(local / r"Google\Chrome\Application\chrome.exe")),
        ("Chromium", str(pf / r"Chromium\Application\chrome.exe")),
        ("Chromium", str(pf86 / r"Chromium\Application\chrome.exe")),
        ("Chromium", str(local / r"Chromium\Application\chrome.exe")),
        ("Microsoft Edge", str(pf86 / r"Microsoft\Edge\Application\msedge.exe")),
        ("Microsoft Edge", str(pf / r"Microsoft\Edge\Application\msedge.exe")),
        ("Microsoft Edge", str(local / r"Microsoft\Edge\Application\msedge.exe")),
        ("Microsoft Edge Beta", str(pf86 / r"Microsoft\Edge Beta\Application\msedge.exe")),
        ("Microsoft Edge Beta", str(pf / r"Microsoft\Edge Beta\Application\msedge.exe")),
        ("Microsoft Edge Beta", str(local / r"Microsoft\Edge Beta\Application\msedge.exe")),
        ("Brave Browser", str(pf / r"BraveSoftware\Brave-Browser\Application\brave.exe")),
        ("Brave Browser", str(local / r"BraveSoftware\Brave-Browser\Application\brave.exe")),
        ("Vivaldi", str(local / r"Vivaldi\Application\vivaldi.exe")),
        ("Opera", str(roaming / r"Opera Software\Opera Stable\launcher.exe")),
        ("Opera GX", str(roaming / r"Opera Software\Opera GX Stable\launcher.exe")),
    ]


# Cached detected browser name for user-facing messages
_detected_browser_name: str | None = None


def get_browser_display_name() -> str:
    """Return the display name of the browser that will be (or was) launched."""
    global _detected_browser_name
    if _detected_browser_name:
        return _detected_browser_name
    return "browser"


# Map config values to display names used in candidate tables
_BROWSER_CONFIG_MAP: dict[str, list[str]] = {
    "chrome": ["Google Chrome"],
    "arc": ["Arc"],
    "brave": ["Brave Browser"],
    "dia": ["Dia"],
    "comet": ["Comet"],
    "edge": ["Microsoft Edge"],
    "edge-beta": ["Microsoft Edge Beta"],
    "chromium": ["Chromium"],
    "vivaldi": ["Vivaldi"],
    "opera": ["Opera", "Opera GX"],
}


def _get_preferred_browser() -> str:
    """Read the auth.browser config setting (default: 'auto')."""
    try:
        from notebooklm_tools.utils.config import load_config

        return load_config().auth.browser.lower().strip()
    except Exception:
        return "auto"


def _get_preferred_browser_path() -> str:
    """Read the optional explicit Chromium executable path."""
    try:
        from notebooklm_tools.utils.config import load_config

        return load_config().auth.browser_path.strip()
    except Exception:
        return ""


def _get_chromium_path(preferred: str | None = None) -> str | None:
    """Return the path/executable for the first available Chromium-based browser.

    Respects the ``auth.browser`` config setting when ``preferred`` is omitted:
    - ``auto`` (default): tries browsers in priority order.
    - A specific name (e.g. ``brave``): tries that browser first, then
      falls back to the full priority list if not found.

    Set via ``nlm config set auth.browser <name>`` or ``NLM_BROWSER`` env var.
    Valid names: auto, chrome, arc, brave, dia, comet, edge, edge-beta, chromium, vivaldi, opera.
    """
    global _detected_browser_name
    if preferred is None:
        preferred = _get_preferred_browser()
        if preferred not in {"auto", *_BROWSER_CONFIG_MAP}:
            preferred = "auto"
    preferred = preferred.lower().strip()

    if preferred not in {"auto", *_BROWSER_CONFIG_MAP}:
        return None

    preferred_names = _BROWSER_CONFIG_MAP.get(preferred, [])

    def _found(name: str, path: str, fallback: bool = False) -> str:
        """Record detected browser name and return the path."""
        global _detected_browser_name
        _detected_browser_name = name
        if fallback:
            _logger.info("Preferred browser not found, falling back to %s", name)
        else:
            _logger.info("Using preferred browser: %s", name)
        return path

    explicit_path = _get_preferred_browser_path()
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        is_executable = candidate.is_file() and (
            platform.system() == "Windows" or os.access(candidate, os.X_OK)
        )
        if is_executable:
            return _found("Custom Chromium browser", str(candidate))
        _logger.error("Configured browser path is not an executable file: %s", candidate)
        return None

    system = platform.system()

    if system == "Darwin":
        candidates = _macos_browser_candidates()
        if preferred_names:
            for name, path in candidates:
                if name in preferred_names and Path(path).exists():
                    return _found(name, path)
        for name, path in candidates:
            if Path(path).exists():
                return _found(name, path, fallback=bool(preferred_names))
        return None

    elif system == "Linux":
        if preferred_names:
            for name, exe in _LINUX_BROWSER_CANDIDATES:
                full_path = shutil.which(exe)
                if name in preferred_names and full_path:
                    return _found(name, full_path)
        for name, exe in _LINUX_BROWSER_CANDIDATES:
            full_path = shutil.which(exe)
            if full_path:
                return _found(name, full_path, fallback=bool(preferred_names))
        return None

    elif system == "Windows":
        candidates = _windows_browser_candidates()
        if preferred_names:
            for name, path in candidates:
                if name in preferred_names and Path(path).exists():
                    return _found(name, path)
        for name, path in candidates:
            if Path(path).exists():
                return _found(name, path, fallback=bool(preferred_names))
        return None

    return None


def get_chrome_path() -> str | None:
    """Return the path/executable for the first available Chromium-based browser."""
    return _get_chromium_path()


def _is_snap_browser(browser_path: str) -> bool:
    """Detect if a browser binary is a Snap package.

    Snap packages have AppArmor confinement that prevents access to
    arbitrary directories. We need to detect this and use a snap-accessible
    profile directory instead.

    Detection methods:
    - Path starts with /snap/ (direct snap binary)
    - Binary is a symlink or wrapper pointing to /snap/
    - Binary path contains /snap/bin/ (snap command wrapper)
    """
    if not browser_path:
        return False

    browser_text = str(browser_path).replace("\\", "/")

    # Direct snap path or snap binary wrapper
    if "/snap/" in browser_text or browser_text.startswith("/snap/"):
        return True

    # Check if it's a symlink pointing to a snap path. Normalize the resolved
    # path text because tests can simulate POSIX paths while running on Windows.
    try:
        resolved_text = str(Path(browser_path).resolve()).replace("\\", "/")
        if "/snap/" in resolved_text or resolved_text.startswith("/snap/"):
            return True
    except (OSError, RuntimeError):
        pass

    return False


def get_snap_common_dir(browser_path: str) -> Path | None:
    """Get the snap common directory for a snap-installed browser.

    Snap packages can only write to specific directories like
    ~/snap/<snap-name>/common/. This returns that directory if the
    browser is a snap, or None if it's not.
    """
    if not _is_snap_browser(browser_path):
        return None

    # Extract snap name from path (e.g., /snap/chromium/3444/... -> chromium).
    # Normalize to POSIX separators so Linux-path simulations work on Windows.
    try:
        resolved_text = str(Path(browser_path).resolve()).replace("\\", "/")
        parts = [part for part in resolved_text.split("/") if part]
        for index, part in enumerate(parts):
            if part == "snap" and index + 1 < len(parts):
                snap_name = parts[index + 1]
                if snap_name in ("chromium", "google-chrome", "firefox"):
                    return get_home_dir() / "snap" / snap_name / "common"
        for part in parts:
            if part in ("chromium", "google-chrome", "firefox"):
                return get_home_dir() / "snap" / part / "common"
    except (OSError, RuntimeError):
        pass

    # Fallback: try common snap names
    for snap_name in ("chromium", "google-chrome"):
        snap_common = get_home_dir() / "snap" / snap_name / "common"
        if snap_common.exists():
            return snap_common

    return None


def get_supported_browsers() -> list[str]:
    """Return a deduplicated, ordered list of browser display-names for the
    current platform.  Used to build human-readable error messages that are
    always in sync with what :func:`get_chrome_path` actually searches for.
    """
    system = platform.system()
    seen: set[str] = set()
    names: list[str] = []
    if system == "Darwin":
        pairs = _macos_browser_candidates()
    elif system == "Linux":
        pairs = _LINUX_BROWSER_CANDIDATES
    else:
        pairs = _windows_browser_candidates()
    for name, _ in pairs:
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


# Import Chrome profile directory from unified config
from notebooklm_tools.utils.config import get_chrome_profile_dir  # noqa: E402


def is_profile_locked(profile_name: str = "default", profile_dir: Path | None = None) -> bool:
    """Check if the Chrome profile is locked (Chrome is using it).

    Args:
        profile_name: NLM profile name (used if profile_dir is None)
        profile_dir: Explicit profile directory path (overrides profile_name)
    """
    if profile_dir is None:
        profile_dir = get_chrome_profile_dir(profile_name)
    lock_file = profile_dir / "SingletonLock"
    return lock_file.exists()


def _get_process_cmdline(pid: int) -> str | None:
    """Best-effort process command line for Chrome ownership checks."""
    system = platform.system()
    if system == "Linux":
        try:
            raw = Path(f"/proc/{pid}/cmdline").read_bytes()
            return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
        except OSError:
            return None
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            return None
    if system == "Windows":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine',
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                cmd = result.stdout.strip()
                return cmd if cmd else None
        except Exception:
            return None
    return None


def _get_cmdline_flag_value(cmdline: str, flag: str) -> str | None:
    """Extract a command-line flag value from raw process command text."""
    pattern = rf"(?:^|\s){re.escape(flag)}(?:=|\s+)(?:\"([^\"]*)\"|'([^']*)'|(\S+))"
    match = re.search(pattern, cmdline)
    if not match:
        return None
    return next(group for group in match.groups() if group is not None)


def _mapped_chrome_owns_profile(pid: int | None, profile_name: str, port: int) -> bool:
    """Return True when the mapped PID was launched with this profile's user-data-dir."""
    if pid is None:
        return True

    chrome_path = get_chrome_path()
    if chrome_path:
        profile_dir = _get_profile_dir_for_launch(chrome_path, profile_name)
    else:
        from notebooklm_tools.utils.config import get_chrome_profile_dir

        profile_dir = get_chrome_profile_dir(profile_name)

    cmdline = _get_process_cmdline(pid)
    if cmdline is None:
        # Can't verify ownership — fail closed so we never attach to a foreign CDP listener.
        return False

    normalized_cmdline = cmdline.replace("\\", "/")
    profile_path = str(profile_dir).replace("\\", "/")
    debug_port = _get_cmdline_flag_value(normalized_cmdline, "--remote-debugging-port")
    user_data_dir = _get_cmdline_flag_value(normalized_cmdline, "--user-data-dir")

    if debug_port != str(port):
        return False

    return user_data_dir == profile_path


def _listener_pid(port: int) -> int | None:
    """Return the PID listening on a local TCP port, if it can be determined."""
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        f"(Get-NetTCPConnection -LocalPort {int(port)} -State Listen "
                        "-ErrorAction SilentlyContinue | Select-Object -First 1 "
                        "-ExpandProperty OwningProcess)"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode == 0:
                text = result.stdout.strip()
                return int(text) if text.isdigit() else None
            return None

        # macOS/Linux: prefer lsof; fall back to fuser on Linux.
        for cmd in (
            ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"],
            ["fuser", f"{int(port)}/tcp"],
        ):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode not in (0, 1):
                continue
            # lsof -t prints one PID per line; fuser may print "12345" or "12345/tcp:"
            for token in re.findall(r"\d+", (result.stdout or "") + " " + (result.stderr or "")):
                return int(token)
    except Exception:
        return None
    return None


def _profile_owned_cdp_listener(port: int, profile_name: str) -> bool:
    """Return whether the local CDP listener belongs to the requested profile."""
    pid = _listener_pid(port)
    return pid is not None and _mapped_chrome_owns_profile(pid, profile_name, port)


def find_existing_nlm_chrome(
    port_range: range = CDP_PORT_RANGE,
    profile_name: str = "default",
    include_headless: bool = False,
) -> tuple[int | None, str | None]:
    """Find an existing NLM Chrome instance for a specific profile.

    Uses the port-to-profile mapping to only reconnect to Chrome instances
    that belong to the requested profile, preventing cross-profile
    contamination. When the map is empty or stale, scans the local CDP port
    range and reuses a listener only after verifying it was launched with this
    profile's ``--user-data-dir`` (Issue #277).

    Args:
        port_range: Range of ports to scan.
        profile_name: Only reuse Chrome instances launched for this profile.
        include_headless: Reuse profile-owned headless browsers too. Interactive
            login flows keep this false; browser-backed RPC transport sets it true.

    Returns:
        The port number and debugger URL if found, (None, None) otherwise
    """

    port_map = _read_port_map()

    # First, check mapped ports for the target profile (fast path)
    for port_str, entry in port_map.items():
        if entry.get("profile") != profile_name:
            continue
        port = int(port_str)
        version_info = _fetch_cdp_version(port, timeout=1)
        if not version_info:
            # Mapped but not responding — stale entry, clean it up
            _clear_port_map(port)
            continue

        ua = version_info.get("User-Agent", "")
        if "Headless" in ua and not include_headless:
            _logger.debug("Skipping headless mapped browser on port %d", port)
            _clear_port_map(port)
            continue

        pid = entry.get("pid")
        if not _mapped_chrome_owns_profile(pid, profile_name, port):
            _logger.debug(
                "Mapped Chrome on port %d (pid=%s) does not own profile '%s'; clearing",
                port,
                pid,
                profile_name,
            )
            _clear_port_map(port)
            continue

        debugger_url = _normalize_ws_url(version_info.get("webSocketDebuggerUrl"))
        if debugger_url:
            _logger.debug(f"Reusing mapped Chrome on port {port} for profile '{profile_name}'")
            return port, debugger_url

        _clear_port_map(port)

    # Map miss / stale map: scan live CDP listeners and adopt only profile-owned ones.
    for port in port_range:
        version_info = _fetch_cdp_version(port, timeout=1)
        if not version_info:
            continue

        ua = version_info.get("User-Agent", "")
        if "Headless" in ua and not include_headless:
            _logger.debug("Skipping headless unmapped browser on port %d", port)
            continue

        pid = _listener_pid(port)
        if pid is None or not _mapped_chrome_owns_profile(pid, profile_name, port):
            _logger.debug(
                "Ignoring unmapped CDP on port %d (pid=%s) for profile '%s'",
                port,
                pid,
                profile_name,
            )
            continue

        debugger_url = _normalize_ws_url(version_info.get("webSocketDebuggerUrl"))
        if not debugger_url:
            continue

        _write_port_map(port, profile_name, pid)
        _logger.debug(
            "Reusing unmapped profile-owned Chrome on port %d for profile '%s'",
            port,
            profile_name,
        )
        return port, debugger_url

    return None, None


def find_any_existing_cdp_browser(
    port_range: range = CDP_PORT_RANGE,
) -> tuple[int | None, str | None]:
    """Find a single reachable non-headless CDP browser in our local port range.

    This is a fallback for environments where the browser is already running
    with remote debugging enabled but wasn't launched by this tool, so no
    port-map entry exists yet.

    Headless browsers are skipped because they typically belong to other
    automation tools (e.g. Perplexity MCP, Playwright) and cannot be used
    for interactive sign-in.
    """
    matches: list[tuple[int, str]] = []
    for port in port_range:
        version_info = _fetch_cdp_version(port, timeout=1)
        if not version_info:
            continue
        ua = version_info.get("User-Agent", "")
        if "Headless" in ua:
            _logger.debug("Skipping headless browser on port %d", port)
            continue
        debugger_url = _normalize_ws_url(version_info.get("webSocketDebuggerUrl"))
        if debugger_url:
            matches.append((port, debugger_url))

    if len(matches) == 1:
        return matches[0]
    return None, None


def _get_profile_dir_for_launch(chrome_path: str, profile_name: str = "default") -> Path:
    """Get the correct Chrome profile directory for launch.

    For snap browsers, returns a snap-accessible directory.
    For non-snap browsers, returns the standard profile directory.

    Args:
        chrome_path: Path to the browser executable
        profile_name: NLM profile name

    Returns:
        Path to the appropriate Chrome profile directory.
    """
    if _is_snap_browser(chrome_path):
        from notebooklm_tools.utils.config import get_snap_chrome_profile_dir

        snap_common = get_snap_common_dir(chrome_path)
        profile_dir = get_snap_chrome_profile_dir(profile_name, snap_common)
        _logger.debug("Snap browser detected, using snap-accessible profile: %s", profile_dir)
    else:
        profile_dir = get_chrome_profile_dir(profile_name)
    return profile_dir


def launch_chrome_process(
    port: int = CDP_DEFAULT_PORT, headless: bool = False, profile_name: str = "default"
) -> subprocess.Popen | None:
    """Launch Chrome and return process handle."""
    chrome_path = get_chrome_path()
    if not chrome_path:
        return None

    profile_dir = _get_profile_dir_for_launch(chrome_path, profile_name)

    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile_dir}",
        f"--remote-allow-origins=http://127.0.0.1:{port}",
    ]

    if platform.system() == "Windows":
        args.append("--disable-features=msEdgeStartupBoost")

    if headless:
        args.append("--headless=new")

    # Never attach unread PIPEs to Chrome: noisy stdout/stderr can fill the OS
    # pipe buffer and deadlock the browser, and inherited stderr pipes can hang
    # startup-failure reads after a launcher handoff. Capture stderr in a temp
    # file so startup diagnostics remain available without blocking.
    stderr_file = None
    try:
        stderr_file = tempfile.TemporaryFile()  # noqa: SIM115
    except OSError:
        stderr_file = None

    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": stderr_file if stderr_file is not None else subprocess.DEVNULL,
    }

    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    try:
        _logger.debug("Launching browser: %s on port %d", chrome_path, port)
        process = subprocess.Popen(args, **kwargs)
        if stderr_file is not None:
            process._nlm_stderr_file = stderr_file  # type: ignore[attr-defined]
        return process
    except Exception as e:
        if stderr_file is not None:
            with contextlib.suppress(Exception):
                stderr_file.close()
        _logger.error(
            "Failed to launch browser at '%s' on port %d: %s",
            chrome_path,
            port,
            e,
        )
        return None


# Module-level Chrome state for termination and reconnection
_chrome_process: subprocess.Popen | None = None
_chrome_port: int | None = None


def launch_chrome(
    port: int = CDP_DEFAULT_PORT, headless: bool = False, profile_name: str = "default"
) -> bool:
    """Launch Chrome with remote debugging enabled."""
    global _chrome_process, _chrome_port
    _chrome_process = launch_chrome_process(port, headless, profile_name)
    _chrome_port = port if _chrome_process else None
    if _chrome_process is not None:
        _write_port_map(port, profile_name, _chrome_process.pid)
    return _chrome_process is not None


def terminate_chrome(process: subprocess.Popen | None = None, port: int | None = None) -> bool:
    """Terminate the Chrome process launched by this module.

    This releases the profile lock so headless auth can work later.

    Returns:
        True if Chrome was terminated, False if no process to terminate.
    """
    global _chrome_process, _chrome_port, _cached_ws, _cached_ws_url
    process = process or _chrome_process
    port = port or _chrome_port
    if process is None:
        return False

    # Attempt graceful shutdown via CDP to prevent "Restore Pages" warnings on next launch
    try:
        debugger_url = _cached_ws_url or (get_debugger_url(port) if port else None)
        if debugger_url:
            execute_cdp_command(debugger_url, "Browser.close")
        else:
            process.terminate()
    except Exception:
        pass  # Ignore connection drops or failures during close

    with _cdp_ws_lock:
        _reset_cached_ws_unlocked()

    try:
        # Wait up to 5 seconds for the graceful shutdown to finish
        process.wait(timeout=5)
    except Exception:
        # If it didn't close in time, force terminate
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                process.kill()
            with contextlib.suppress(Exception):
                process.wait(timeout=5)
    finally:
        _close_process_streams(process)

    # Clean up port map
    effective_port = port or _chrome_port
    if effective_port:
        _clear_port_map(effective_port)

    if process == _chrome_process:
        _chrome_process = None
        _chrome_port = None
    return True


def close_profile_owned_cdp_browser(cdp_url: str, profile_name: str = "default") -> bool:
    """Close a local CDP browser only after proving profile ownership.

    This is intended for externally managed browsers. It never touches a
    remote endpoint, and it refuses to clear the port mapping if a different
    process replaces the managed listener while shutdown is in progress.
    """
    try:
        cdp_http_url = normalize_cdp_http_url(cdp_url)
        parsed = urlparse(cdp_http_url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"} or host not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            return False
        if parsed.port is None:
            return False

        port = parsed.port
        pid = _listener_pid(port)
        if pid is None or not _mapped_chrome_owns_profile(pid, profile_name, port):
            return False

        version = _fetch_cdp_version(port, timeout=1)
        debugger_url = _normalize_ws_url((version or {}).get("webSocketDebuggerUrl"))
        if debugger_url:
            with contextlib.suppress(Exception):
                execute_cdp_command(debugger_url, "Browser.close")
            for _ in range(20):
                time.sleep(0.1)
                if not _pid_is_alive(pid):
                    replacement_pid = _listener_pid(port)
                    if replacement_pid not in (None, pid):
                        return False
                    _clear_port_map(port)
                    return True

        if not _pid_is_alive(pid):
            replacement_pid = _listener_pid(port)
            if replacement_pid not in (None, pid):
                return False
            _clear_port_map(port)
            return True

        current_pid = _listener_pid(port)
        if current_pid != pid or not _mapped_chrome_owns_profile(pid, profile_name, port):
            return False

        _kill_process(pid)
        for _ in range(20):
            time.sleep(0.1)
            if not _pid_is_alive(pid):
                if _listener_pid(port) is not None:
                    return False
                _clear_port_map(port)
                return True
        return False
    except Exception:
        return False


def _fetch_cdp_version(port: int, *, timeout: int = 5) -> dict | None:
    """Fetch /json/version from a CDP endpoint, returning parsed JSON or None."""
    try:
        response = httpx_client.get(f"{_cdp_http_base(port)}/json/version", timeout=timeout)
        return response.json()
    except Exception:
        return None


def get_debugger_url(
    port: int = CDP_DEFAULT_PORT, *, tries: int = 1, timeout: int = 5
) -> str | None:
    """Get the WebSocket debugger URL for Chrome."""
    for attempt in range(tries):
        data = _fetch_cdp_version(port, timeout=timeout)
        if data:
            return _normalize_ws_url(data.get("webSocketDebuggerUrl"))
        if attempt < tries - 1:
            time.sleep(1)
    return None


def get_pages_by_cdp_url(cdp_http_url: str) -> list[dict]:
    """Get list of open pages from an arbitrary CDP HTTP endpoint."""
    try:
        response = httpx_client.get(f"{cdp_http_url}/json", timeout=5)
        return response.json()
    except Exception:
        return []


def find_or_create_notebooklm_page_by_cdp_url(cdp_http_url: str) -> dict | None:
    """Find an existing NotebookLM page or create one on a given CDP endpoint."""
    pages = get_pages_by_cdp_url(cdp_http_url)

    for page in pages:
        url = page.get("url", "")
        if _is_notebooklm_url(url):
            return page

    try:
        encoded_url = quote(get_notebooklm_url(), safe="")
        response = httpx_client.put(
            f"{cdp_http_url}/json/new?{encoded_url}",
            timeout=15,
        )
        if response.status_code == 200 and response.text.strip():
            return response.json()
        _logger.debug("Failed to create page via PUT /json/new?url: HTTP %s", response.status_code)
    except Exception as e:
        _logger.debug("Exception creating page via PUT /json/new?url: %s", e)

    try:
        response = httpx_client.put(f"{cdp_http_url}/json/new", timeout=10)
        if response.status_code == 200 and response.text.strip():
            page = response.json()
            ws_url = _normalize_ws_url(page.get("webSocketDebuggerUrl"))
            if ws_url:
                navigate_to_url(ws_url, get_notebooklm_url())
            return page
        _logger.debug(
            "Failed to create blank page via PUT /json/new: HTTP %s", response.status_code
        )
    except Exception as e:
        _logger.debug("Exception creating blank page via PUT /json/new: %s", e)

    # All creation attempts failed — reuse only a safe blank/new-tab page.
    _logger.debug("Falling back to reusing a blank existing page.")
    for page in pages:
        url = page.get("url", "")
        if url in ("about:blank", "chrome://newtab/"):
            ws_url = _normalize_ws_url(page.get("webSocketDebuggerUrl"))
            if ws_url:
                _logger.debug("Reusing page with url %s", url)
                navigate_to_url(ws_url, get_notebooklm_url())
                return page

    return None


def find_or_create_notebooklm_page(port: int = CDP_DEFAULT_PORT) -> dict | None:
    """Find an existing NotebookLM page or create a new one."""
    return find_or_create_notebooklm_page_by_cdp_url(_cdp_http_base(port))


@contextlib.contextmanager
def _cdp_websocket_without_proxy_env():
    """Unset HTTP proxy env vars for this CDP WebSocket connect only.

    ``websocket-client`` reads ``HTTP_PROXY`` / ``HTTPS_PROXY`` whenever
    ``http_proxy_host`` is omitted or explicitly ``None`` (see
    ``websocket._url.get_proxy_info``), so those kwargs do not disable proxies.
    CDP must always reach the local browser, never an upstream proxy.

    Complements :data:`httpx_client` (Issue #119); see PR #157 discussion.
    """
    import os

    keys = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    )
    saved: dict[str, str] = {}
    for key in keys:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ[key] = value


def execute_cdp_command(
    ws_url: str,
    method: str,
    params: dict | None = None,
    *,
    retry: bool = True,
    response_timeout: float = 30,
) -> dict:
    """Execute a CDP command via WebSocket.

    Args:
        ws_url: WebSocket URL for the page
        method: CDP method name (e.g., "Network.getCookies")
        params: Optional parameters for the command

    Returns:
        The result of the CDP command
    """
    global _cached_ws, _cached_ws_url

    if retry:
        # Retry once in case of stale cached connection. Close stale sockets so
        # the second attempt cannot reuse a broken descriptor.
        try:
            return execute_cdp_command(
                ws_url,
                method,
                params,
                retry=False,
                response_timeout=response_timeout,
            )
        except Exception:
            pass  # Fall through to reconnect below

    with _cdp_ws_lock:
        if ws_url != _cached_ws_url or not _cached_ws:
            _reset_cached_ws_unlocked()

            # suppress_origin=True is required for some managed Chrome/CDP endpoints
            # (e.g. OpenClaw browser profile) that reject default Origin headers.
            try:
                with _cdp_websocket_without_proxy_env():
                    ws = websocket.create_connection(ws_url, timeout=30, suppress_origin=True)
            except TypeError:
                # Older websocket-client versions may not support suppress_origin.
                with _cdp_websocket_without_proxy_env():
                    ws = websocket.create_connection(ws_url, timeout=30)
            _cached_ws = ws
            _cached_ws_url = ws_url
        else:
            ws = _cached_ws

        command_id = _next_cdp_command_id()
        command = {"id": command_id, "method": method, "params": params or {}}
        ws.send(json.dumps(command))

        # Wait for response with matching ID. Long-running in-page fetches, such as
        # streamed notebook queries, can legitimately exceed the default 30s wait.
        ws.settimeout(response_timeout)
        try:
            while True:
                response = json.loads(ws.recv())
                if response.get("id") != command_id:
                    continue
                if "error" in response:
                    raise RuntimeError(f"CDP command '{method}' failed: {response['error']}")
                return response.get("result", {})
        except websocket.WebSocketTimeoutException as err:
            _reset_cached_ws_unlocked()
            raise TimeoutError(
                f"CDP command '{method}' timed out after {response_timeout:g}s waiting for response"
            ) from err
        except Exception:
            _reset_cached_ws_unlocked()
            raise


def get_page_cookies(ws_url: str) -> list[dict]:
    """Get all cookies for the page via CDP.

    This is the key function that avoids keychain access!
    Uses Network.getAllCookies CDP command to get cookies for all domains.

    Returns:
        List of cookie objects (dicts) including name, value, domain, path, etc.
    """
    result = execute_cdp_command(ws_url, "Network.getAllCookies")
    return result.get("cookies", [])


def get_page_html(ws_url: str) -> str:
    """Get the page HTML to extract CSRF token."""
    execute_cdp_command(ws_url, "Runtime.enable")
    result = execute_cdp_command(
        ws_url, "Runtime.evaluate", {"expression": "document.documentElement.outerHTML"}
    )
    return result.get("result", {}).get("value", "")


def get_document_root(ws_url: str) -> dict:
    """Get the document root node."""
    return execute_cdp_command(ws_url, "DOM.getDocument")["root"]


def query_selector(ws_url: str, node_id: int, selector: str) -> int | None:
    """Find a node ID using a CSS selector."""
    result = execute_cdp_command(
        ws_url, "DOM.querySelector", {"nodeId": node_id, "selector": selector}
    )
    return result.get("nodeId") if result.get("nodeId") != 0 else None


def get_current_url(ws_url: str) -> str:
    """Get the current page URL."""
    execute_cdp_command(ws_url, "Runtime.enable")
    result = execute_cdp_command(ws_url, "Runtime.evaluate", {"expression": "window.location.href"})
    return result.get("result", {}).get("value", "")


def navigate_to_url(ws_url: str, url: str) -> None:
    """Navigate the page to a URL."""
    execute_cdp_command(ws_url, "Page.enable")
    execute_cdp_command(ws_url, "Page.navigate", {"url": url})


def _is_notebooklm_url(url: str) -> bool:
    """Check if a URL belongs to a NotebookLM host.

    This must inspect only the hostname. Google sign-in URLs often contain
    ``continue=https://notebooklm.google.com/...`` in the query string, but
    those pages are still accounts.google.com pages and should not be treated
    as NotebookLM tabs.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host in {
        "notebooklm.google.com",
        "notebook.google.com",
        "notebooklm.cloud.google.com",
        "notebook.cloud.google.com",
        "vertexaisearch.cloud.google.com",
    }


def is_logged_in(url: str) -> bool:
    """Check login status by parsed URL hostname.

    Inspect the parsed hostname so query strings such as
    ``?original_referer=https://accounts.google.com#`` (which NotebookLM
    appends to the redirect target right after Google sign-in) are not
    mistaken for an accounts.google.com redirect.
    """
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if host == "accounts.google.com" or host.endswith(".accounts.google.com"):
        return False
    return _is_notebooklm_url(url)


def extract_build_label(html: str) -> str:
    """Extract the build label (bl) from page HTML.

    Google embeds the current build label under the 'cfb2h' key in the page's
    inline configuration JSON. This value is used as the 'bl' URL parameter
    in batchexecute and query requests.
    """
    match = re.search(r'"cfb2h":"([^"]+)"', html)
    return match.group(1) if match else ""


def extract_csrf_token(html: str) -> str:
    """Extract CSRF token from page HTML."""
    match = re.search(r'"SNlM0e":"([^"]+)"', html)
    return match.group(1) if match else ""


def extract_session_id(html: str) -> str:
    """Extract session ID from page HTML."""
    patterns = [
        r'"FdrFJe":"(-?\d+)"',
        r'f\.sid["\s:=]+["\']?(-?\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


def extract_email(html: str) -> str:
    """Extract user email from page HTML."""
    # Try various patterns Google uses to embed the email
    patterns = [
        r'"oPEP7c":"([^"]+@[^"]+)"',  # Google's internal email field
        r'data-email="([^"]+)"',  # data-email attribute
        r'"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"',  # Generic email in quotes
    ]
    for pattern in patterns:
        matches = re.findall(pattern, html)
        for match in matches:
            # Filter out common false positives
            if "@google.com" not in match and "@gstatic" not in match:  # noqa: SIM102
                if "@" in match and "." in match.split("@")[-1]:
                    return match
    return ""


def _kill_process(pid: int) -> None:
    """Best effort to kill a process by PID."""
    import os
    import signal

    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def _kill_stale_nlm_browsers() -> None:
    """Kill browser processes started by NLM that are no longer responsive on CDP."""
    port_map = _read_port_map()
    for port_str, entry in list(port_map.items()):
        pid = entry.get("pid")
        if pid:
            # Check if process is alive but CDP is unresponsive
            debugger_url = get_debugger_url(int(port_str), timeout=1)
            if not debugger_url:
                # Process alive but CDP dead — zombie, kill it
                _logger.debug(f"Killing stale NLM browser process {pid} on port {port_str}")
                _kill_process(pid)
                _clear_port_map(int(port_str))


def _clear_managed_profile_directory(profile_name: str, profile_dir: Path) -> None:
    """Close a profile-owned browser and remove its managed user-data directory."""
    existing_port, debugger_url = find_existing_nlm_chrome(
        profile_name=profile_name,
        include_headless=True,
    )
    if existing_port is not None and debugger_url:
        closed = close_profile_owned_cdp_browser(_cdp_http_base(existing_port), profile_name)
        if not closed:
            remaining_port, remaining_url = find_existing_nlm_chrome(
                profile_name=profile_name,
                include_headless=True,
            )
            if remaining_port is not None and remaining_url:
                raise AuthenticationError(
                    message=f"Could not close browser profile '{profile_name}'",
                    hint=(
                        "Close the managed NotebookLM browser for this profile and run "
                        "'nlm login --clear' again."
                    ),
                )

    for _ in range(20):
        if not profile_dir.exists():
            return
        shutil.rmtree(profile_dir, ignore_errors=True)
        if not profile_dir.exists():
            return
        time.sleep(0.1)

    raise AuthenticationError(
        message=f"Could not clear browser profile '{profile_name}'",
        hint=(
            "Close the managed NotebookLM browser for this profile and run "
            "'nlm login --clear' again."
        ),
    )


def extract_cookies_via_cdp(
    port: int = CDP_DEFAULT_PORT,
    auto_launch: bool = True,
    wait_for_login: bool = True,
    login_timeout: int = 300,
    profile_name: str = "default",
    clear_profile: bool = False,
) -> dict[str, Any]:
    """Extract cookies and tokens from Chrome via CDP.

    This is the main entry point for CDP-based authentication.

    Args:
        port: Chrome DevTools port
        auto_launch: If True, launch Chrome if not running
        wait_for_login: If True, wait for user to log in
        login_timeout: Max seconds to wait for login
        profile_name: NLM profile name (each gets its own Chrome user-data-dir)
        clear_profile: If True, delete the Chrome user-data-dir before launching

    Returns:
        Dict with cookies, csrf_token, session_id, and email

    Raises:
        AuthenticationError: If extraction fails
    """
    if clear_profile:
        chrome_path = get_chrome_path()
        if chrome_path:
            profile_dir = _get_profile_dir_for_launch(chrome_path, profile_name)
        else:
            from notebooklm_tools.utils.config import get_chrome_profile_dir

            profile_dir = get_chrome_profile_dir(profile_name)
        _clear_managed_profile_directory(profile_name, profile_dir)

    # Check if Chrome is running with debugging
    # First, try to find an existing instance on any port in our range
    _kill_stale_nlm_browsers()

    reused_existing = False
    existing_port, debugger_url = None, None
    if not clear_profile:
        existing_port, debugger_url = find_existing_nlm_chrome(profile_name=profile_name)

    if existing_port:
        port = existing_port
        reused_existing = True

    if not debugger_url and auto_launch:
        chrome_path = get_chrome_path()
        if not chrome_path:
            browser_names = get_supported_browsers()
            if len(browser_names) > 1:
                browsers = ", ".join(browser_names[:-1]) + f", or {browser_names[-1]}"
            else:
                browsers = browser_names[0] if browser_names else "Google Chrome"
            raise AuthenticationError(
                message="No supported browser found",
                hint=f"Install {browsers}, or use 'nlm login --manual' to import cookies from a file.",
            )

        # Get the correct profile directory for this browser (snap-aware)
        profile_dir = _get_profile_dir_for_launch(chrome_path, profile_name)

        if is_profile_locked(profile_name, profile_dir):
            # Profile locked but no browser found on known ports - stale lock?
            raise AuthenticationError(
                message="The NLM auth profile is locked but no browser instance was found",
                hint=f"Close any stuck browser processes or delete the SingletonLock file in the {profile_name} browser profile.",
            )

        # Find an available port
        try:
            port = find_available_port()
        except RuntimeError as e:
            raise AuthenticationError(
                message=str(e),
                hint="Close some browser instances and try again.",
            ) from e

        if not launch_chrome(port, profile_name=profile_name):
            raise AuthenticationError(
                message="Failed to launch browser",
                hint="Try 'nlm login --manual' to import cookies from a file.",
            )

        # Snap Chromium and some Chromium forks can take noticeably longer
        # to expose CDP than the browser window itself takes to appear.
        # If the child already exited (Chrome handoff to an existing profile
        # lock), stop polling the unbound port immediately (#277).
        debugger_url = None
        launcher_exit_attempt: int | None = None
        for attempt in range(30):
            launcher_exited = _chrome_process is not None and _chrome_process.poll() is not None
            if launcher_exited and launcher_exit_attempt is None:
                launcher_exit_attempt = attempt

            debugger_url = get_debugger_url(port, tries=1, timeout=1)
            if debugger_url:
                launcher_exited = _chrome_process is not None and _chrome_process.poll() is not None
                if launcher_exited and launcher_exit_attempt is None:
                    launcher_exit_attempt = attempt
                # On Windows, the launcher can exit after handing off to an
                # existing Chrome process. Do not accept a late listener
                # until its PID is proven to own this profile.
                if (
                    platform.system() != "Windows"
                    or not launcher_exited
                    or _profile_owned_cdp_listener(port, profile_name)
                ):
                    break
                debugger_url = None

            if launcher_exited and (
                platform.system() != "Windows"
                or (launcher_exit_attempt is not None and attempt - launcher_exit_attempt >= 5)
            ):
                break
            if attempt < 29:
                time.sleep(1)

    if not debugger_url:
        startup_error = _summarize_browser_startup_failure(_chrome_process)
        handed_off = (
            not reused_existing
            and _chrome_process is not None
            and _chrome_process.poll() is not None
        )
        if handed_off:
            # Chrome was already running under a different process, so the browser we
            # launched handed off to it and exited immediately without ever binding the
            # remote-debugging port.
            hint = (
                "Fully quit Chrome (all windows) and run 'nlm login' again. "
                "If that doesn't help, use 'nlm login --manual' to import cookies from a file."
            )
            if startup_error:
                hint = f"{hint} ({startup_error})"
            raise AuthenticationError(
                message=(
                    "Chrome is already running, so the sign-in browser couldn't start "
                    "with remote debugging."
                ),
                hint=hint,
            )
        hint = "Use 'nlm login --manual' to import cookies from a file."
        if startup_error:
            hint = f"{hint} Browser startup error: {startup_error}"
        raise AuthenticationError(
            message=f"Cannot connect to browser on port {port}",
            hint=hint,
        )
    result = extract_cookies_from_page(_cdp_http_base(port), wait_for_login, login_timeout)
    result["reused_existing"] = reused_existing
    return result


def extract_cookies_via_existing_cdp(
    cdp_url: str,
    wait_for_login: bool = True,
    login_timeout: int = 300,
) -> dict[str, Any]:
    """Extract auth cookies from an already-running Chrome CDP endpoint.

    This is used for provider-style auth integrations (e.g. OpenClaw-managed
    browser profiles) where Chrome lifecycle is managed externally.
    """
    try:
        cdp_http_url = normalize_cdp_http_url(cdp_url)
    except ValueError as e:
        raise AuthenticationError(message=str(e)) from e

    try:
        version = httpx_client.get(f"{cdp_http_url}/json/version", timeout=8)
        version.raise_for_status()
    except Exception as e:
        raise AuthenticationError(
            message=f"Cannot connect to CDP endpoint: {cdp_http_url}",
            hint="Ensure the browser is running and CDP is reachable.",
        ) from e
    return extract_cookies_from_page(cdp_http_url, wait_for_login, login_timeout)


def _wait_for_page_ready(ws_url: str, timeout: int = 30) -> tuple[str, bool]:
    """Poll until NotebookLM page is fully loaded (session tokens in DOM).

    Returns (html, ready) tuple.
    """
    start = time.time()
    while time.time() - start < timeout:
        try:
            html = get_page_html(ws_url)
            if extract_session_id(html) or extract_build_label(html):
                return html, True
        except Exception:
            pass
        time.sleep(1)
    # Timeout — return last HTML we got
    try:
        return get_page_html(ws_url), False
    except Exception:
        return "", False


def extract_cookies_from_page(
    cdp_http_url: str,
    wait_for_login: bool = True,
    login_timeout: int = 300,
) -> dict[str, Any]:
    from notebooklm_tools.core.auth import validate_cookies

    page = find_or_create_notebooklm_page_by_cdp_url(cdp_http_url)
    if not page:
        raise AuthenticationError(
            message="Failed to open NotebookLM page",
            hint=f"Try manually navigating to {get_base_url()} and try again.",
        )

    ws_url = _normalize_ws_url(page.get("webSocketDebuggerUrl"))
    if not ws_url:
        raise AuthenticationError(
            message="No WebSocket URL for NotebookLM page",
            hint="The target browser may need a restart.",
        )

    # Navigate to NotebookLM if needed
    current_url = page.get("url", "")
    if not _is_notebooklm_url(current_url):
        navigate_to_url(ws_url, get_notebooklm_url())

    # Anonymous landing pages use the same host and have page metadata too.
    # Only accept the app's CSRF token together with signed-in Google cookies.
    start_time = time.time()
    last_log_at = 0
    if wait_for_login:
        _logger.warning("Waiting for sign-in in browser window (timeout: %ds)...", login_timeout)
    while True:
        try:
            current_url = get_current_url(ws_url)
            if is_logged_in(current_url):
                html = get_page_html(ws_url)
                cookies = get_page_cookies(ws_url)
                csrf_token = extract_csrf_token(html)
                if csrf_token and validate_cookies(cookies):
                    break
        except Exception:
            pass
        elapsed = time.time() - start_time
        if not wait_for_login or elapsed >= login_timeout:
            raise AuthenticationError(
                message="Login timeout" if wait_for_login else "Browser is not signed in",
                hint="Please log in to NotebookLM in the connected browser window.",
            )
        if int(elapsed) - last_log_at >= 30:
            last_log_at = int(elapsed)
            _logger.warning("Still waiting for sign-in... (%ds elapsed)", last_log_at)
        time.sleep(0.5)

    session_id = extract_session_id(html)
    email = extract_email(html)
    build_label = extract_build_label(html)
    base_host = urlparse(current_url).hostname or ""

    return {
        "cookies": cookies,
        "csrf_token": csrf_token,
        "session_id": session_id,
        "email": email,
        "build_label": build_label,
        "base_host": base_host,
    }


# =============================================================================
# Headless Authentication (for automatic token refresh)
# =============================================================================


def has_chrome_profile(profile_name: str = "default") -> bool:
    """Check if a Chrome profile with saved login exists.

    Returns True if the profile directory exists and has login cookies,
    indicating that the user has previously authenticated.

    Checks both standard and snap-accessible profile directories.
    """

    def _profile_has_cookie_db(profile_dir: Path) -> bool:
        cookie_paths = (
            profile_dir / "Default" / "Cookies",
            profile_dir / "Default" / "Network" / "Cookies",
        )
        return any(path.exists() for path in cookie_paths)

    # Check standard profile directory
    profile_dir = get_chrome_profile_dir(profile_name)
    if _profile_has_cookie_db(profile_dir):
        return True

    # Check snap-accessible profile directory
    chrome_path = get_chrome_path()
    if chrome_path and _is_snap_browser(chrome_path):
        from notebooklm_tools.utils.config import get_snap_chrome_profile_dir

        snap_common = get_snap_common_dir(chrome_path)
        snap_profile_dir = get_snap_chrome_profile_dir(profile_name, snap_common)
        if _profile_has_cookie_db(snap_profile_dir):
            return True

    return False


def cleanup_chrome_profile_cache(profile_name: str = "default") -> int:
    """Remove unnecessary cache directories to minimize profile size.

    Keeps cookies and login data intact while removing caches that can
    grow to hundreds of MB. Safe to run after successful authentication.

    Args:
        profile_name: The profile name to clean up.

    Returns:
        Number of bytes freed.
    """
    # Cache directories that are safe to remove (not needed for auth)
    cache_dirs = [
        "Cache",
        "Code Cache",
        "Service Worker",
        "GPUCache",
        "DawnWebGPUCache",
        "DawnGraphiteCache",
        "ShaderCache",
        "GrShaderCache",
    ]

    bytes_freed = 0

    def _clean_profile_dir(profile_dir: Path) -> int:
        freed = 0
        default_dir = profile_dir / "Default"
        for cache_dir in cache_dirs:
            cache_path = default_dir / cache_dir
            if cache_path.exists():
                try:
                    size = sum(f.stat().st_size for f in cache_path.rglob("*") if f.is_file())
                    shutil.rmtree(cache_path, ignore_errors=True)
                    freed += size
                except Exception:
                    pass
        return freed

    # Clean standard profile directory
    profile_dir = get_chrome_profile_dir(profile_name)
    bytes_freed += _clean_profile_dir(profile_dir)

    # Clean snap-accessible profile directory
    chrome_path = get_chrome_path()
    if chrome_path and _is_snap_browser(chrome_path):
        from notebooklm_tools.utils.config import get_snap_chrome_profile_dir

        snap_common = get_snap_common_dir(chrome_path)
        snap_profile_dir = get_snap_chrome_profile_dir(profile_name, snap_common)
        bytes_freed += _clean_profile_dir(snap_profile_dir)

    return bytes_freed


def _validate_headless_candidate(tokens: "Any", profile_name: str) -> bool:
    """Prove extracted browser credentials work before replacing saved auth."""
    from notebooklm_tools.core.client import NotebookLMClient

    try:
        with NotebookLMClient(
            cookies=tokens.cookies,
            csrf_token=tokens.csrf_token,
            session_id=tokens.session_id,
            build_label=tokens.build_label or "",
            base_host=tokens.base_host or "",
            profile_name=profile_name,
            # Candidate validation must not persist token rotations before the
            # candidate itself has been accepted and saved by run_headless_auth.
            is_env_auth=True,
        ) as client:
            # A missing/malformed RPC payload must not authenticate a candidate.
            # An empty but valid notebook list is still acceptable.
            client.list_notebooks(require_valid_response=True)
        return True
    except Exception:
        return False


def _run_headless_auth_unlocked(
    port: int = 9223,
    timeout: int = 30,
    profile_name: str = "default",
    expected_revision: str | None = None,
    force: bool | None = None,
    raise_on_error: bool = False,
    expected_file_fingerprint: str | None = None,
) -> "Any | None":
    """Run authentication in headless mode (no user interaction).

    This only works if the Chrome profile already has saved Google login.
    The Chrome process is automatically terminated after token extraction.

    Used for automatic token refresh when cached tokens expire.

    Args:
        port: Chrome DevTools port (use different port to avoid conflicts)
        timeout: Maximum time to wait for auth extraction
        profile_name: The profile name to use for Chrome
        expected_revision: Optional expected revision for compare-and-save
        force: If True, overwrite without revision check
        raise_on_error: If True, surface safe browser infrastructure failures
            instead of collapsing them to None.

    Returns:
        AuthTokens if successful, None if failed or no saved login
    """
    # Import here to avoid circular imports
    from notebooklm_tools.core.auth import AuthTokens, save_tokens_to_cache, validate_cookies
    from notebooklm_tools.core.credential_store import CredentialStoreError
    from notebooklm_tools.utils.config import get_auth_storage_mode

    # Preflight store availability for protected profile before launching browser
    if get_auth_storage_mode(profile_name) == "protected":
        from notebooklm_tools.core.credential_store import (
            BackendUnavailableError,
            CredentialStore,
        )

        store = CredentialStore()
        if not store.is_available():
            raise BackendUnavailableError(
                f"Cannot access credentials for profile '{profile_name}': "
                "OS credential store is locked or unavailable.\n"
                "Unlock your OS keystore / run this from your desktop session and retry. "
                f"To stop using Protected mode for this profile, run 'nlm auth storage set file --profile {profile_name}' from your desktop session."
            )

    # Check if profile exists with saved login
    if not has_chrome_profile(profile_name):
        if raise_on_error:
            raise AuthenticationError(
                message=f"No saved browser profile is available for '{profile_name}'",
                hint="Run 'nlm login' once in a desktop session to create and sign in the managed browser profile.",
            )
        return None

    chrome_process: subprocess.Popen | None = None
    chrome_was_running = False

    try:
        # Try to connect only to a profile-owned existing Chrome first.
        existing_port, debugger_url = find_existing_nlm_chrome(
            port_range=range(port, port + 1),
            profile_name=profile_name,
            include_headless=True,
        )

        if existing_port is not None and debugger_url:
            # Chrome already running for this profile - use existing instance
            port = existing_port
            chrome_was_running = True
        else:
            # No Chrome running - launch in headless mode. Pick a free port
            # first so a foreign process already holding the default port can't
            # make Chrome bind elsewhere (e.g. [::1]) while we probe the wrong
            # listener (issue #330).
            port = find_available_port(starting_from=port)
            chrome_process = launch_chrome_process(port, headless=True, profile_name=profile_name)
            if not chrome_process:
                if raise_on_error:
                    raise AuthenticationError(
                        message="Failed to launch the headless authentication browser",
                        hint="Run 'nlm login' in a desktop session to re-authenticate.",
                    )
                return None

            # Wait for Chrome debugger to be ready
            debugger_url = get_debugger_url(port, tries=5)
            if not debugger_url:
                if raise_on_error:
                    raise AuthenticationError(
                        message=f"Cannot connect to the headless authentication browser on port {port}",
                        hint="Run 'nlm login' in a desktop session to re-authenticate.",
                    )
                return None

        # Find or create NotebookLM page
        page = find_or_create_notebooklm_page(port)
        if not page:
            if raise_on_error:
                raise AuthenticationError(
                    message="Could not open NotebookLM in the headless authentication browser",
                    hint="Run 'nlm login' in a desktop session to refresh the managed browser profile.",
                )
            return None

        ws_url = _normalize_ws_url(page.get("webSocketDebuggerUrl"))
        if not ws_url:
            if raise_on_error:
                raise AuthenticationError(
                    message="NotebookLM page did not expose a usable DevTools websocket",
                    hint="Run 'nlm login' in a desktop session to refresh the managed browser profile.",
                )
            return None

        # Poll for login completion (navigation is async)
        start = time.time()
        logged_in = False
        while time.time() - start < timeout:
            try:
                current_url = get_current_url(ws_url)
                if is_logged_in(current_url):
                    logged_in = True
                    break
            except Exception:
                pass
            time.sleep(1)

        if not logged_in:
            # Not logged in - headless can't help without a prior visible sign-in.
            if raise_on_error:
                raise AuthenticationError(
                    message=f"Saved browser profile '{profile_name}' is not signed in to NotebookLM",
                    hint="Run 'nlm login' in a desktop session once, then headless refresh can reuse that managed browser session.",
                )
            return None

        # Wait for full page load
        html, ready = _wait_for_page_ready(ws_url, timeout=timeout)
        if not ready:
            if raise_on_error:
                raise AuthenticationError(
                    message="NotebookLM did not finish loading in the headless authentication browser",
                    hint="Run 'nlm login' in a desktop session to refresh the managed browser profile.",
                )
            return None

        # Keep the raw list so per-domain values survive profile storage.
        cookies_list = get_page_cookies(ws_url)

        if not validate_cookies(cookies_list):
            if raise_on_error:
                raise AuthenticationError(
                    message="Saved browser profile did not expose the required NotebookLM cookies",
                    hint="Run 'nlm login' in a desktop session to refresh the managed browser profile.",
                )
            return None

        # Get page HTML for CSRF extraction
        # html already fetched by _wait_for_page_ready
        csrf_token = extract_csrf_token(html)
        session_id = extract_session_id(html)
        base_host = urlparse(current_url).hostname or ""

        # Build a candidate first. Do not replace saved credentials until
        # an authenticated NotebookLM RPC proves the extracted browser session
        # works outside the browser context.
        tokens = AuthTokens(
            cookies=cookies_list,
            csrf_token=csrf_token or "",
            session_id=session_id or "",
            base_host=base_host,
            extracted_at=time.time(),
        )
        if not _validate_headless_candidate(tokens, profile_name):
            if raise_on_error:
                raise AuthenticationError(
                    message="NotebookLM rejected the credentials extracted from the saved browser profile",
                    hint="Run 'nlm login' in a desktop session to refresh the managed browser profile.",
                )
            return None

        save_kwargs: dict[str, Any] = {
            "profile_name": profile_name,
            "force": False if force is None else force,
        }
        if expected_file_fingerprint is not None:
            save_kwargs["expected_file_fingerprint"] = expected_file_fingerprint
        if expected_revision is not None:
            save_kwargs["expected_revision"] = expected_revision
        rev = save_tokens_to_cache(tokens, **save_kwargs)
        tokens.revision = rev

        # Clean up cache to minimize profile size
        cleanup_chrome_profile_cache(profile_name)

        return tokens

    except CredentialStoreError:
        raise
    except AuthenticationError:
        if raise_on_error:
            raise
        return None
    except RuntimeError as exc:
        if raise_on_error:
            raise AuthenticationError(
                message=str(exc),
                hint="Run 'nlm login' in a desktop session to re-authenticate.",
            ) from exc
        return None
    except Exception as exc:
        if raise_on_error:
            raise AuthenticationError(
                message=f"Headless browser refresh failed ({type(exc).__name__})",
                hint="Run 'nlm login' in a desktop session to re-authenticate.",
            ) from exc
        return None

    finally:
        # IMPORTANT: Only terminate Chrome if we launched it
        # Don't terminate if we connected to existing Chrome instance
        if chrome_process and not chrome_was_running:
            terminate_chrome(chrome_process, port)


def run_headless_auth(
    port: int = 9223,
    timeout: int = 30,
    profile_name: str = "default",
    expected_revision: str | None = None,
    force: bool | None = None,
    raise_on_error: bool = False,
    expected_file_fingerprint: str | None = None,
) -> "Any | None":
    """Serialize headless recovery per profile across CLI and MCP processes.

    A second caller reuses a validated credential revision saved by the winner
    instead of launching a second browser against the same Google session.
    Locks are separate from credential-storage locks to avoid nesting them
    across the browser/network operation.
    """
    from filelock import FileLock
    from filelock import Timeout as FileLockTimeout

    from notebooklm_tools.core.auth import auth_state_fingerprint, load_cached_tokens
    from notebooklm_tools.utils.config import get_storage_dir, validate_profile_name

    validate_profile_name(profile_name, strict=False)
    before = load_cached_tokens(profile_name=profile_name)
    before_revision = expected_revision or getattr(before, "revision", None)
    before_file_fingerprint = auth_state_fingerprint(before)
    before_extracted = getattr(before, "extracted_at", 0) or 0
    lock_dir = get_storage_dir() / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(lock_dir / f"{profile_name}.recovery.lock", timeout=max(1, timeout))

    try:
        with lock:
            updated = load_cached_tokens(profile_name=profile_name)
            revision_changed = updated is not None and (
                (before_revision is not None and updated.revision != before_revision)
                or (before_revision is None and (updated.extracted_at or 0) > before_extracted)
            )
            if (
                not force
                and revision_changed
                and _validate_headless_candidate(updated, profile_name)
            ):
                return updated
            return _run_headless_auth_unlocked(
                port=port,
                timeout=timeout,
                profile_name=profile_name,
                expected_revision=before_revision,
                force=force,
                raise_on_error=raise_on_error,
                expected_file_fingerprint=before_file_fingerprint,
            )
    except FileLockTimeout as exc:
        if raise_on_error:
            raise AuthenticationError(
                message=f"Headless authentication is already running for profile '{profile_name}'",
                hint="Retry after the concurrent refresh completes.",
            ) from exc
        return None
