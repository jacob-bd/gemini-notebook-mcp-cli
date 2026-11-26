"""Firefox profile utilities for NotebookLM authentication."""

from __future__ import annotations

import contextlib
import logging
import os
import platform
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from notebooklm_tools.core.exceptions import AuthenticationError
from notebooklm_tools.utils.config import get_base_url, get_firefox_profile_dir

_logger = logging.getLogger(__name__)


def get_firefox_path() -> str | None:
    """Return the Firefox executable path for the current platform."""
    system = platform.system()
    if system == "Darwin":
        candidates = (
            Path("/Applications/Firefox.app/Contents/MacOS/firefox"),
            Path.home() / "Applications/Firefox.app/Contents/MacOS/firefox",
        )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None
    if system == "Windows":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            base_path = os.environ.get(variable)
            if not base_path:
                continue
            candidate = Path(base_path) / "Mozilla Firefox" / "firefox.exe"
            if candidate.exists():
                return str(candidate)
        local_app_data_path = os.environ.get("LOCALAPPDATA")
        if not local_app_data_path:
            return None
        candidate = Path(local_app_data_path) / "Mozilla Firefox" / "firefox.exe"
        return str(candidate) if candidate.exists() else None
    return shutil.which("firefox") or shutil.which("firefox-esr")


def ensure_firefox_available() -> str:
    """Return the Firefox executable or raise an actionable error."""
    firefox = get_firefox_path()
    if not firefox:
        raise AuthenticationError(
            message="Firefox is not installed",
            hint="Install Firefox, then run 'nlm login' again.",
        )
    return firefox


def _is_google_cookie_host(host: str) -> bool:
    normalized = host.lstrip(".").lower()
    return normalized == "google.com" or normalized.endswith(".google.com")


def _read_google_cookies(profile_dir: Path) -> list[dict[str, Any]]:
    """Snapshot Firefox's cookie store so it can be read while Firefox is open."""
    cookie_db = profile_dir / "cookies.sqlite"
    if not cookie_db.exists():
        return []

    try:
        with (
            contextlib.closing(
                sqlite3.connect(f"{cookie_db.as_uri()}?mode=ro", uri=True)
            ) as source,
            contextlib.closing(sqlite3.connect(":memory:")) as snapshot,
        ):
            source.backup(snapshot)
            rows = snapshot.execute(
                "SELECT name, value, host, path, expiry, isSecure, isHttpOnly FROM moz_cookies"
            ).fetchall()
    except sqlite3.Error as exc:
        _logger.debug("Could not read Firefox cookies: %s", exc)
        return []

    return [
        {
            "name": name,
            "value": value,
            "domain": host,
            "path": path,
            "expires": expiry,
            "secure": bool(is_secure),
            "httpOnly": bool(is_http_only),
        }
        for name, value, host, path, expiry, is_secure, is_http_only in rows
        if isinstance(host, str) and _is_google_cookie_host(host)
    ]


def _launch_firefox(firefox_path: str, profile_dir: Path) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            [
                firefox_path,
                "-no-remote",
                "-profile",
                str(profile_dir),
                f"{get_base_url()}/",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise AuthenticationError(
            message="Failed to launch Firefox",
            hint="Close any Firefox windows using the NLM auth profile and try again.",
        ) from exc


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(Exception):
        process.terminate()
        process.wait(timeout=5)
        return
    with contextlib.suppress(Exception):
        process.kill()
        process.wait(timeout=5)


def _wait_for_google_cookies(profile_dir: Path, timeout: int) -> list[dict[str, Any]]:
    from notebooklm_tools.core.auth import validate_cookies

    deadline = time.monotonic() + timeout
    last_log_at = 0
    while time.monotonic() < deadline:
        cookies = _read_google_cookies(profile_dir)
        if validate_cookies(cookies):
            return cookies
        elapsed = int(time.monotonic() - (deadline - timeout))
        if elapsed - last_log_at >= 30:
            last_log_at = elapsed
            _logger.warning("Still waiting for Firefox sign-in... (%ds elapsed)", elapsed)
        time.sleep(0.5)
    raise AuthenticationError(
        message="Login timeout",
        hint="Please log in to Gemini Notebook in the Firefox window.",
    )


def has_firefox_profile(profile_name: str = "default") -> bool:
    """Return whether the NLM Firefox profile has a cookie store."""
    return (get_firefox_profile_dir(profile_name) / "cookies.sqlite").exists()


def extract_cookies_via_firefox(
    *,
    wait_for_login: bool = True,
    login_timeout: int = 300,
    profile_name: str = "default",
    clear_profile: bool = False,
) -> dict[str, Any]:
    """Launch normal Firefox and capture Google cookies from its isolated profile."""
    from notebooklm_tools.core.auth import validate_cookies

    firefox_path = ensure_firefox_available()
    profile_dir = get_firefox_profile_dir(profile_name)
    if clear_profile and profile_dir.exists():
        shutil.rmtree(profile_dir)
        profile_dir = get_firefox_profile_dir(profile_name)

    process: subprocess.Popen[bytes] | None = None
    try:
        if wait_for_login:
            process = _launch_firefox(firefox_path, profile_dir)
            cookies = _wait_for_google_cookies(profile_dir, login_timeout)
        else:
            cookies = _read_google_cookies(profile_dir)
            if not validate_cookies(cookies):
                raise AuthenticationError(
                    message="Firefox profile is not signed in",
                    hint="Run 'nlm login' interactively to sign in to Gemini Notebook.",
                )
        return {
            "cookies": cookies,
            "csrf_token": "",
            "session_id": "",
            "email": "",
            "build_label": "",
            "base_host": "",
        }
    finally:
        if process is not None:
            _terminate_process(process)


def run_headless_auth(
    timeout: int = 30,
    profile_name: str = "default",
    expected_revision: str | None = None,
    force: bool | None = None,
    raise_on_error: bool = False,
) -> Any | None:
    """Refresh cached credentials from the saved Firefox profile cookie store."""
    del timeout

    from notebooklm_tools.core.auth import (
        AuthTokens,
        auth_state_fingerprint,
        load_cached_tokens,
        save_tokens_to_cache,
        validate_cookies,
    )
    from notebooklm_tools.core.credential_store import CredentialStoreError
    from notebooklm_tools.utils.config import get_auth_storage_mode

    before = load_cached_tokens(profile_name=profile_name)
    before_revision = expected_revision or getattr(before, "revision", None)
    before_file_fingerprint = auth_state_fingerprint(before)

    # Preflight store availability for protected profile
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

    if not has_firefox_profile(profile_name):
        if raise_on_error:
            raise AuthenticationError(
                message=f"No saved Firefox profile is available for '{profile_name}'",
                hint="Run 'nlm login' once in a desktop session to create and sign in the managed browser profile.",
            )
        return None

    try:
        cookies = _read_google_cookies(get_firefox_profile_dir(profile_name))
        if not validate_cookies(cookies):
            if raise_on_error:
                raise AuthenticationError(
                    message="Saved Firefox profile did not expose the required NotebookLM cookies",
                    hint="Run 'nlm login' in a desktop session to refresh the managed browser profile.",
                )
            return None
        tokens = AuthTokens(cookies=cookies, extracted_at=time.time())
        save_kwargs: dict[str, Any] = {
            "profile_name": profile_name,
            "force": False if force is None else force,
            "expected_file_fingerprint": before_file_fingerprint,
        }
        if before_revision is not None:
            save_kwargs["expected_revision"] = before_revision
        rev = save_tokens_to_cache(tokens, **save_kwargs)
        tokens.revision = rev
        return tokens
    except (CredentialStoreError, AuthenticationError):
        raise
    except Exception as exc:
        if raise_on_error:
            raise AuthenticationError(
                message=f"Headless Firefox refresh failed ({type(exc).__name__})",
                hint="Run 'nlm login' in a desktop session to re-authenticate.",
            ) from exc
        return None
