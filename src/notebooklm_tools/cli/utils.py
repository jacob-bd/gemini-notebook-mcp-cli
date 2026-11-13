import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import typer
from rich.console import Console

from notebooklm_tools import __version__
from notebooklm_tools.services.auth import AuthManager
from notebooklm_tools.services.client import NotebookLMClient
from notebooklm_tools.utils.config import get_config, get_storage_dir
from notebooklm_tools.utils.versioning import is_newer_version


def make_console(**kwargs) -> "Console":
    """Create a Rich Console that is safe on Windows legacy codepage terminals.

    Windows consoles using cp1251/cp1252 etc. cannot encode certain Unicode
    characters that Rich uses by default (e.g. checkmark ✓ U+2713). Setting
    ``safe_box=True`` replaces box-drawing chars with ASCII fallbacks.
    Rich also auto-detects the terminal encoding on Windows via ``PYTHONIOENCODING``
    or the system locale — but this ensures we never crash even without that override.

    See: https://github.com/jacob-bd/gemini-notebook-mcp-cli/issues/105
    """
    kwargs.setdefault("safe_box", True)
    if sys.platform == "win32":
        # Avoid Rich legacy Windows renderer path that encodes with cp1252 (Issue #156).
        kwargs.setdefault("legacy_windows", False)
    return Console(**kwargs)


console = make_console()


def get_client(profile: str | None = None) -> NotebookLMClient:
    """Get an authenticated NotebookLM client.

    Args:
        profile: Optional profile name. Uses config default_profile if not specified.

    An explicit profile takes precedence over environment cookies. Without a
    profile, tries environment cookies, then the configured default profile.
    """
    # 1. Environment auth applies only when no profile was explicitly selected.
    env_cookies = os.environ.get("NOTEBOOKLM_COOKIES")
    if env_cookies and not profile:
        return NotebookLMClient(
            cookies=extract_cookies_from_string(env_cookies),
        )

    # 2. Try loading specified profile, or fall back to config default
    if not profile:
        profile = get_config().auth.default_profile
    manager = AuthManager(profile)
    if not manager.profile_exists():
        console.print(
            f"[red]Error:[/red] Profile '{manager.profile_name}' not found. Run 'nlm login' first."
        )
        raise typer.Exit(1)

    try:
        p = manager.load_profile()
        return NotebookLMClient(
            cookies=p.cookies,
            csrf_token=p.csrf_token or "",
            session_id=p.session_id or "",
            build_label=p.build_label or "",
            base_host=p.base_host or "",
            profile_name=profile,
            auth_revision=getattr(p, "revision", None),
            is_env_auth=False,
        )
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[yellow]Authentication error:[/yellow] {e}")
        console.print("Please run: [bold]nlm login[/bold]")
        raise typer.Exit(1) from e


def handle_error(e: Exception, json_output: bool = False) -> None:
    """Standard error handler for CLI commands."""
    from notebooklm_tools.cli.formatters import print_json
    from notebooklm_tools.services.errors import NLMError, ServiceError

    if isinstance(e, typer.Exit):
        raise e

    msg = str(e)
    hint = getattr(e, "hint", None)

    if isinstance(e, ServiceError):
        msg = e.user_message
    elif isinstance(e, NLMError):
        msg = e.message

    if json_output:
        err = {"status": "error", "error": msg}
        if hint:
            err["hint"] = hint
        print_json(err)
    else:
        if isinstance(e, (ServiceError, NLMError)):
            console.print(f"[red]Error:[/red] {msg}")
            if hint:
                console.print(f"\n[dim]Hint: {hint}[/dim]")
        else:
            # Unexpected error
            console.print(f"[red]Unexpected Error:[/red] {msg}")

    raise typer.Exit(1)


def extract_cookies_from_string(cookie_str: str) -> dict[str, str]:
    """Helper to parse raw cookie string."""
    cookies = {}
    if not cookie_str:
        return cookies
    for item in cookie_str.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            if key:
                cookies[key] = value.strip()
    return cookies


# ========== Version Check Utilities ==========


def _get_cache_path() -> Path | None:
    """Get path to version check cache file, or None if inaccessible."""
    cache_dir = get_storage_dir() / "cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        return None
    return cache_dir / "update_check.json"


def _get_cached_version_info() -> dict | None:
    """Load cached version info if still valid (within 24 hours)."""
    cache_path = _get_cache_path()
    if cache_path is None or not cache_path.exists():
        return None

    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)

        # Check if cache is still valid (24 hours = 86400 seconds)
        if time.time() - data.get("checked_at", 0) < 86400:
            return data
    except (json.JSONDecodeError, OSError):
        pass

    return None


def _save_version_cache(latest_version: str) -> None:
    """Save version info to cache."""
    cache_path = _get_cache_path()
    if cache_path is None:
        return
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "latest_version": latest_version,
                    "checked_at": time.time(),
                },
                f,
            )
    except OSError:
        pass  # Silently ignore cache write failures


def _fetch_latest_version() -> str | None:
    """Fetch latest version from PyPI with 2 second timeout."""
    try:
        url = "https://pypi.org/pypi/notebooklm-mcp-cli/json"
        req = urllib.request.Request(url, headers={"User-Agent": "notebooklm-mcp-cli"})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            return data.get("info", {}).get("version")
    except Exception:
        return None


def check_for_updates() -> tuple[bool, str | None]:
    """Check if a new version is available.

    Returns:
        Tuple of (update_available, latest_version).
        Uses cached result if available and fresh.
    """
    # Check cache first
    cached = _get_cached_version_info()
    if cached:
        latest = cached.get("latest_version")
        if latest:
            return is_newer_version(__version__, latest), latest

    # Fetch from PyPI
    latest = _fetch_latest_version()
    if latest:
        _save_version_cache(latest)
        return is_newer_version(__version__, latest), latest

    return False, None


def print_update_notification() -> None:
    """Print update notification if available. Call after command execution."""
    # Only show in TTY (not when piping output)
    import sys

    if not sys.stdout.isatty():
        return

    update_available, latest = check_for_updates()
    if update_available and latest:
        console.print()
        console.print(
            f"[dim]🔔 Update available:[/dim] [cyan]{__version__}[/cyan] → [green]{latest}[/green]. "
            f"[dim]Run[/dim] [bold]uv tool upgrade notebooklm-mcp-cli[/bold] [dim]to update.[/dim]"
        )


def is_tool_on_system(
    binary: str | None = None,
    root_dirs: list[Path] | None = None,
) -> bool:
    """Check whether an AI tool is installed on this system.

    Returns True if either signal is found:
    1. ``binary`` is on PATH (via ``shutil.which``)
    2. Any directory in ``root_dirs`` exists

    Shared by ``nlm skill install`` (detection before installing skills) and
    ``nlm setup`` (detection before configuring MCP servers).
    """
    if binary and shutil.which(binary):
        return True
    return any(d.exists() for d in (root_dirs or []))


def print_storage_mode_notification() -> None:
    """Print one-time notice about Protected mode if eligible.

    Order of checks:
    (a) "already shown/answered" flag: is_cli_notice_shown()
    (b) TTY: sys.stderr.isatty() (the tip goes to stderr so piped stdout stays clean)
    (c) cheap session hints via should_offer_protection() (skip SSH, container, headless Linux)
    (d) file-mode check: default profile must be configured and in file mode
    (e) real probe at most once per install (30-day cache in notices.json)
    """
    from notebooklm_tools.services.notices import (
        get_protect_answer,
        is_cli_notice_shown,
        mark_cli_notice_shown,
    )

    # (a) already shown flag
    if is_cli_notice_shown():
        return

    # (b) TTY check
    if not sys.stderr.isatty():
        return

    from notebooklm_tools.services.auth import AuthManager
    from notebooklm_tools.services.auth_storage import CredentialStore
    from notebooklm_tools.utils.config import get_auth_storage_mode, get_config

    try:
        profile = get_config().auth.default_profile
        if not AuthManager(profile).profile_exists():
            return
        if get_protect_answer(profile) is not None:
            return
        if get_auth_storage_mode(profile) != "file":
            return
    except Exception:
        return

    store = CredentialStore()
    if not store.should_offer_protection(profile_name=profile):
        return

    make_console(stderr=True).print(
        "\n🔒 New (optional): protect your saved login in your OS keystore → nlm auth storage set protected",
        soft_wrap=True,
        highlight=False,
    )
    mark_cli_notice_shown()
