"""Auth tools - Authentication management."""

import os
import time
import urllib.parse
from http.cookies import SimpleCookie

from notebooklm_tools.services.errors import AuthenticationError, CredentialStoreError

from ._utils import (
    ESSENTIAL_COOKIES,
    ResultDict,
    error_result,
    get_client,
    logged_tool,
    reset_client,
)


@logged_tool()
def refresh_auth(profile: str | None = None) -> ResultDict:
    """Reload auth for the requested profile without switching the active account.

    Call this after running `nlm login` to pick up new tokens,
    or attempt headless recovery with the profile's saved browser.
    An explicit profile does not switch the MCP server's active account.

    Returns status indicating if tokens were refreshed successfully.
    """

    def reload_active_client() -> None:
        from notebooklm_tools.utils.config import get_config

        if profile is None or profile == get_config().auth.default_profile:
            reset_client()
            get_client()

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

        cached = load_cached_tokens(profile_name=profile) if profile else load_cached_tokens()
        stale_cached: tuple[str, str | None] | None = None
        headless_failure: AuthenticationError | None = None
        if cached:
            # A disk reload is only success if the credentials still work. If
            # they are stale, keep going: the saved browser profile may still be
            # able to mint fresh credentials via the headless recovery path.
            from notebooklm_tools.services.auth import credentials_are_usable

            usable, status, detail = (
                credentials_are_usable(force=True, profile=profile)
                if profile
                else credentials_are_usable(force=True)
            )
            if usable:
                reload_active_client()
                return {
                    "status": "success",
                    "message": "Auth tokens reloaded from disk cache and validated.",
                }
            stale_cached = (status, detail)

        # Try headless auth if the configured default Chrome profile exists.
        # Skipped when the user opted out (e.g. Workspace accounts whose session
        # is revoked when the saved browser profile is relaunched, issue #330).
        headless_disabled = os.environ.get("NOTEBOOKLM_DISABLE_HEADLESS_REFRESH") == "1"
        if not headless_disabled:
            try:
                from notebooklm_tools.utils.auth_browser import run_headless_auth
                from notebooklm_tools.utils.config import get_config

                profile_name = profile or get_config().auth.default_profile
                tokens = run_headless_auth(
                    profile_name=profile_name,
                    raise_on_error=True,
                )
                if tokens:
                    reload_active_client()
                    return {
                        "status": "success",
                        "message": "Auth tokens refreshed via headless Chrome.",
                    }
            except CredentialStoreError:
                raise
            except AuthenticationError as exc:
                headless_failure = exc
            except Exception as exc:
                headless_failure = AuthenticationError(
                    message=f"Headless browser refresh failed ({type(exc).__name__})",
                    hint="Run 'nlm login' in a desktop session to re-authenticate.",
                )

        if stale_cached is not None:
            status, detail = stale_cached
            headless_details: dict[str, str] = {}
            if headless_failure is not None:
                reason_text = f"automatic browser refresh failed: {headless_failure.message}"
                headless_details["headless_error"] = headless_failure.message
                if headless_failure.hint:
                    headless_details["headless_hint"] = headless_failure.hint
            else:
                reason_text = (
                    "automatic browser refresh is disabled (NOTEBOOKLM_DISABLE_HEADLESS_REFRESH=1)"
                    if headless_disabled
                    else "the saved browser profile could not refresh it automatically"
                )
            return error_result(
                f"Cached auth is no longer valid and {reason_text}. "
                "Run `nlm login` in a terminal to re-authenticate.",
                status="expired",
                reason=status,
                details=detail,
                **headless_details,
            )

        return {
            "status": "error",
            "error": "No cached tokens found. Run 'nlm login' to authenticate.",
        }
    except CredentialStoreError as exc:
        return error_result(
            str(exc),
            hint=(
                "OS credential store is locked or unavailable. "
                "Unlock your OS keystore / run this from your desktop session and retry."
            ),
        )
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def save_auth_tokens(
    cookies: str,
    csrf_token: str = "",
    session_id: str = "",
    request_body: str = "",
    request_url: str = "",
) -> ResultDict:
    """Save NotebookLM cookies (FALLBACK method - try `nlm login` first!).

    IMPORTANT FOR AI ASSISTANTS:
    - First, run `nlm login` via Bash/terminal (automated, preferred)
    - Only use this tool if the automated CLI fails

    Args:
        cookies: Cookie header from Chrome DevTools (only needed if CLI fails)
        csrf_token: Deprecated - auto-extracted
        session_id: Deprecated - auto-extracted
        request_body: Optional - contains CSRF if extracting manually
        request_url: Optional - contains session ID if extracting manually
    """
    try:
        from notebooklm_tools.services.auth import (
            AuthTokens,
            get_cache_path,
            save_tokens_to_cache,
        )
        from notebooklm_tools.utils.config import (
            get_auth_storage_mode,
            get_config,
            get_profile_dir,
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

        target_profile = get_config().auth.default_profile
        if get_auth_storage_mode(target_profile) == "protected":
            saved_path = get_profile_dir(target_profile, create=False) / "credentials.enc"
        else:
            saved_path = get_cache_path()

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
            "cache_path": str(saved_path),
            "extracted_csrf": bool(csrf_token),
            "extracted_session_id": bool(session_id),
        }
    except CredentialStoreError as exc:
        return error_result(
            str(exc),
            hint=(
                "OS credential store is locked or unavailable. "
                "Unlock your OS keystore / run this from your desktop session and retry."
            ),
        )
    except Exception as e:
        return error_result(str(e))
