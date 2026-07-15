"""Auth tools - Authentication management."""

import os
import time
import urllib.parse
from http.cookies import SimpleCookie

from ._utils import (
    ESSENTIAL_COOKIES,
    ResultDict,
    error_result,
    get_client,
    logged_tool,
    reset_client,
)


@logged_tool()
def refresh_auth() -> ResultDict:
    """Reload auth tokens from disk or run headless re-authentication.

    Call this after running `nlm login` to pick up new tokens,
    or to attempt automatic re-authentication if Chrome profile has saved login.

    Returns status indicating if tokens were refreshed successfully.
    """
    try:
        # If NOTEBOOKLM_COOKIES is set in the environment (e.g. claude_desktop_config.json),
        # it overrides all disk-based auth. Disk reload won't help — the env var wins on
        # every client re-init. Tell the user exactly what to do instead of lying with "success".
        if os.environ.get("NOTEBOOKLM_COOKIES"):
            return error_result(
                "NOTEBOOKLM_COOKIES is set as an environment variable in your MCP config. "
                "This overrides all other auth sources (auth.json, nlm login, save_auth_tokens). "
                "To fix: update the cookie value in your MCP config file "
                "(e.g. claude_desktop_config.json) and restart, "
                "or remove the NOTEBOOKLM_COOKIES env var and use 'nlm login' instead."
            )

        # Try reloading from disk first
        from notebooklm_tools.services.auth import load_cached_tokens

        cached = load_cached_tokens()
        if cached:
            # Honesty check FIRST: reloading tokens from disk is NOT a successful
            # re-auth if those tokens are already dead. Validate live before
            # creating any client, otherwise agents loop on doomed studio calls
            # (and we leave a client object initialized with bad tokens behind).
            from notebooklm_tools.services.auth import credentials_are_usable

            usable, status, detail = credentials_are_usable(force=True)
            if not usable:
                return error_result(
                    "Auth tokens were reloaded from disk but are no longer valid "
                    f"(reason: {status}). A disk reload cannot revive expired "
                    "credentials — run `nlm login` in a terminal to re-authenticate.",
                    status="expired",
                    reason=status,
                    details=detail,
                )
            reset_client()
            get_client()
            return {
                "status": "success",
                "message": "Auth tokens reloaded from disk cache and validated.",
            }

        # Try headless auth if the configured default Chrome profile exists
        try:
            from notebooklm_tools.utils.auth_browser import run_headless_auth
            from notebooklm_tools.utils.config import get_config

            profile_name = get_config().auth.default_profile
            tokens = run_headless_auth(profile_name=profile_name)
            if tokens:
                reset_client()
                get_client()
                return {
                    "status": "success",
                    "message": "Auth tokens refreshed via headless Chrome.",
                }
        except Exception:
            pass

        return {
            "status": "error",
            "error": "No cached tokens found. Run 'nlm login' to authenticate.",
        }
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def save_auth_tokens(
    cookies: str,
    csrf_token: str = "",
    session_id: str = "",
    request_body: str = "",
    request_url: str = "",
    confirm: bool = False,
) -> ResultDict:
    """Save NotebookLM cookies (FALLBACK method - try `nlm login` first!).

    IMPORTANT FOR AI ASSISTANTS:
    - First, run `nlm login` via Bash/terminal (automated, preferred)
    - Only use this tool if the automated CLI fails
    - This tool requires confirm=True to proceed — do not set confirm=True
      unless the user has explicitly approved saving auth tokens

    Args:
        cookies: Cookie header from Chrome DevTools (only needed if CLI fails)
        csrf_token: Deprecated - auto-extracted
        session_id: Deprecated - auto-extracted
        request_body: Optional - contains CSRF if extracting manually
        request_url: Optional - contains session ID if extracting manually
        confirm: Must be True to proceed — prevents automatic cookie overwrites
            by LLM agents without user approval
    """
    if not confirm:
        return error_result(
            "Saving auth tokens requires user confirmation. "
            "Set confirm=True to proceed. This protects against "
            "unintended session hijacking via prompt injection.",
            status="confirmation_required",
        )

    try:
        from notebooklm_tools.services.auth import (
            AuthTokens,
            get_cache_path,
            save_tokens_to_cache,
        )

        # Parse cookie string to dict. Cookie headers are valid with or
        # without spaces after semicolons, so do not split only on '; '.
        try:
            parsed_cookie = SimpleCookie()
            parsed_cookie.load(cookies)
            all_cookies = {key: morsel.value for key, morsel in parsed_cookie.items()}
        except Exception:
            all_cookies = {}
        if not all_cookies:
            all_cookies = {}
            for part in cookies.split(";"):
                if "=" in part:
                    key, value = part.split("=", 1)
                    all_cookies[key.strip()] = value.strip()

        # Validate required cookies
        required = ["SID", "HSID", "SSID", "APISID", "SAPISID"]
        missing = [c for c in required if c not in all_cookies]
        if missing:
            return {
                "status": "error",
                "error": f"Missing required cookies: {missing}",
            }

        # Filter to only essential cookies
        cookie_dict = {k: v for k, v in all_cookies.items() if k in ESSENTIAL_COOKIES}

        # Try to extract CSRF token from request body if provided
        if not csrf_token and request_body:
            body_params = urllib.parse.parse_qs(request_body, keep_blank_values=True)
            csrf_token = body_params.get("at", [""])[0]

        # Try to extract session ID and build label from request URL if provided
        build_label = ""
        if request_url:
            parsed_url = urllib.parse.urlparse(request_url)
            query = parsed_url.query or request_url
            url_params = urllib.parse.parse_qs(query, keep_blank_values=True)
            if not session_id:
                session_id = url_params.get("f.sid", [""])[0]
            build_label = url_params.get("bl", [""])[0]

        # Create and save tokens
        tokens = AuthTokens(
            cookies=cookie_dict,
            csrf_token=csrf_token,
            session_id=session_id,
            build_label=build_label,
            extracted_at=time.time(),
        )
        save_tokens_to_cache(tokens)

        # Reset client so next call uses fresh tokens
        reset_client()

        # Build status message
        if csrf_token and session_id:
            token_msg = "CSRF token and session ID extracted from network request - no page fetch needed! ⚡"
        elif csrf_token:
            token_msg = "CSRF token extracted from network request. Session ID will be auto-extracted on first use."
        elif session_id:
            token_msg = "Session ID extracted from network request. CSRF token will be auto-extracted on first use."
        else:
            token_msg = "CSRF token and session ID will be auto-extracted on first API call (~1-2s one-time delay)."

        return {
            "status": "success",
            "message": f"Saved {len(cookie_dict)} essential cookies (filtered from {len(all_cookies)}). {token_msg}",
            # Note: cache_path intentionally omitted from response to prevent
            # path disclosure that could aid cookie exfiltration.
            "extracted_csrf": bool(csrf_token),
            "extracted_session_id": bool(session_id),
        }
    except Exception as e:
        return error_result(str(e))
