"""Service layer for auth.

Re-exports the low-level auth primitives from `core.auth` and owns the
business-logic pieces that don't belong in core:

- `AuthHealthChecker`, `AuthProbeResult`, `AuthHealthReport` — multi-probe
  health check (homepage + API fallback) with TTL caching and per-probe
  diagnostics.
- `get_auth_health_checker()` — process-wide singleton so the CLI and the
  MCP server share the same 30-second cache.

Thin re-exports of `check_auth`, `load_cached_tokens`, `save_tokens_to_cache`,
`get_cache_path`, `validate_cookies`, `AuthManager`, and `AuthTokens` are
provided so the `cli/` and `mcp/` layers can satisfy the layering rule
(`cli/` and `mcp/` must not import from `core/`).

Monkeypatching of the underlying `core.auth` symbols is preserved by
resolving every wrapper lazily (function wrappers re-resolve on each
call; class symbols re-resolve through PEP 562 `__getattr__`).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from notebooklm_tools.core import auth as _core_auth
from notebooklm_tools.services.auth_replay import (
    AuthReplayDiagnostic,
    AuthReplayProbe,
    diagnose_auth_replay,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AuthHealthChecker",  # defined locally in this module
    "AuthHealthReport",  # defined locally in this module
    "AuthReplayDiagnostic",  # provided by services.auth_replay
    "AuthReplayProbe",  # provided by services.auth_replay
    "AuthManager",  # noqa: F822 — provided lazily via PEP 562 __getattr__
    "AuthProbeResult",  # defined locally in this module
    "AuthTokens",  # noqa: F822 — provided lazily via PEP 562 __getattr__
    "check_auth",
    "confirm_auth_via_api",
    "credentials_are_usable",
    "diagnose_auth_replay",
    "ensure_profile_ready",
    "extract_cookies_from_chrome_export",
    "get_active_auth_mtime",
    "get_auth_health_checker",
    "get_cache_path",
    "get_notebook_count",
    "load_cached_tokens",
    "save_tokens_to_cache",
    "validate_cookies",
]


# ---------------------------------------------------------------------------
# Thin re-exports of low-level auth primitives
# ---------------------------------------------------------------------------


def check_auth(*args, **kwargs):
    """Re-export of `notebooklm_tools.core.auth.check_auth`.

    Resolves the implementation lazily on each call so that monkeypatching
    `notebooklm_tools.core.auth.check_auth` (a common test pattern) is
    observed by callers of this shim.
    """
    return _core_auth.check_auth(*args, **kwargs)


def ensure_profile_ready(profile_name: str | None = None) -> None:
    """Re-export of `notebooklm_tools.core.auth.ensure_profile_ready`."""
    _core_auth.ensure_profile_ready(profile_name=profile_name)


def load_cached_tokens(profile_name: str | None = None):
    """Re-export of `notebooklm_tools.core.auth.load_cached_tokens`."""
    if profile_name is None:
        return _core_auth.load_cached_tokens()
    return _core_auth.load_cached_tokens(profile_name=profile_name)


def save_tokens_to_cache(
    tokens,
    silent: bool = False,
    profile_name: str | None = None,
    expected_revision: str | None = None,
    force: bool = True,
):
    """Re-export of `notebooklm_tools.core.auth.save_tokens_to_cache`."""
    kwargs: dict[str, Any] = {}
    if profile_name is not None:
        kwargs["profile_name"] = profile_name
    if expected_revision is not None:
        kwargs["expected_revision"] = expected_revision
    kwargs["force"] = force
    try:
        return _core_auth.save_tokens_to_cache(tokens, silent=silent, **kwargs)
    except TypeError:
        kwargs.pop("force", None)
        kwargs.pop("expected_revision", None)
        return _core_auth.save_tokens_to_cache(tokens, silent=silent, **kwargs)


def get_cache_path() -> Path:
    """Re-export of `notebooklm_tools.core.auth.get_cache_path`."""
    return _core_auth.get_cache_path()


def validate_cookies(cookies):
    """Re-export of `notebooklm_tools.core.auth.validate_cookies`."""
    return _core_auth.validate_cookies(cookies)


def get_active_auth_mtime() -> float:
    """Return the most recent mtime of any auth storage on disk, or 0.0.

    The CLI/MCP codebase stores auth in two layouts that can coexist:

    - **Modern (multi-profile):** `~/.notebooklm-mcp-cli/profiles/<name>/cookies.json`
      for each profile `<name>` in the profiles directory.
    - **Legacy (single-profile):** `~/.notebooklm-mcp-cli/auth.json` at the
      storage root, used by older installs and some MCP clients.

    The auth-guard mtime check needs to invalidate on a write to ANY of
    these files, not just the one for the "default" profile — because the
    active profile for a given MCP/CLI session can be overridden with
    `--profile`, while the config-level `default_profile` stays put. If
    we only watched the config-default profile's file, an external
    `nlm login --profile <other>` would silently fail to invalidate the
    guard (live-testing caught this exact bug in v0.6.15 prep).

    This function stats every `cookies.json` under `profiles/`, the
    legacy `auth.json` at the storage root, and returns the max mtime.
    A write to any of them invalidates the guard. Returns 0.0 if no auth
    file exists yet (sentinel for "no cache yet").

    Catches all exceptions and returns 0.0 on error: a wrong mtime answer
    is far less harmful than a 500 on `studio_create` from an unrelated
    config error.
    """
    try:
        import contextlib

        from notebooklm_tools.utils.config import get_profiles_dir, get_storage_dir

        candidates = [get_storage_dir() / "auth.json"]
        try:
            profiles_dir = get_profiles_dir()
            candidates.extend(profiles_dir.glob("*/cookies.json"))
        except (OSError, FileNotFoundError):
            pass

        latest = 0.0
        for path in candidates:
            with contextlib.suppress(OSError, FileNotFoundError):
                latest = max(latest, path.stat().st_mtime)
        return latest
    except Exception:
        return 0.0


def get_active_auth_state(profile: str | None = None) -> Any:
    """Return an invalidation state token for active auth storage.

    In protected mode, returns (profile_name, 'protected', revision) where revision
    is read from credentials.enc, guaranteeing that rapid writes within a single
    filesystem mtime tick invalidate the cache.
    In file mode, returns (profile_name, 'file', mtime) or the float mtime,
    preserving main's exact behavior.
    """
    try:
        from notebooklm_tools.core.credential_store import get_envelope_revision
        from notebooklm_tools.utils.config import (
            get_auth_storage_mode,
            get_config,
            get_profile_dir,
        )

        prof = (profile or get_config().auth.default_profile).strip()
        mode = get_auth_storage_mode(prof)
        if mode == "protected":
            enc_file = get_profile_dir(prof, create=False) / "credentials.enc"
            rev = get_envelope_revision(enc_file) if enc_file.exists() else None
            return (prof, "protected", rev)
        return (prof, "file", get_active_auth_mtime())
    except Exception:
        return (profile or "default", "unknown", 0.0)


# Lazy-re-exported core classes. The shim does NOT cache these in module
# globals; a top-level import would poison the cache for any test that
# monkeypatches `core.auth.<Class>` afterward. Resolving on every access
# keeps tests working at the cost of one extra attribute lookup.
_LAZY_CLASS_NAMES = frozenset({"AuthTokens", "AuthManager"})


def extract_cookies_from_chrome_export(cookie_data: str | list[dict]) -> dict[str, str]:
    """Parse a Chrome cookie export. Thin re-export of `core.utils`."""
    from notebooklm_tools.core.utils import extract_cookies_from_chrome_export as _extract

    return _extract(cookie_data)


def __getattr__(name):
    """PEP 562 lazy re-export of class symbols from `core.auth`."""
    if name in _LAZY_CLASS_NAMES:
        from notebooklm_tools.core.auth import AuthManager, AuthTokens

        return {"AuthTokens": AuthTokens, "AuthManager": AuthManager}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Business logic: AuthHealthChecker (multi-probe, cached, with diagnostics)
# ---------------------------------------------------------------------------


@dataclass
class AuthProbeResult:
    """Result from a single health probe (homepage or API).

    Each probe records its own endpoint, latency, and error for
    detailed diagnostics.
    """

    probe: str  # "homepage" or "api"
    valid: bool
    status_code: int | None = None
    latency_ms: float = 0.0
    error: str | None = None
    detail: str | None = None


@dataclass
class AuthHealthReport:
    """Full diagnostic report from AuthHealthChecker.

    Contains all probe results, the final verdict, and timing info
    so callers (server_info, doctor, CLI --check) can render either
    a simple status string or a detailed breakdown.
    """

    valid: bool
    status: str  # "configured" | "stale" | "unverified" | "not_configured"
    probes: list[AuthProbeResult]
    token_age_hours: float | None = None
    profile: str = "default"
    checked_at: float = 0.0
    cached: bool = False


class AuthHealthChecker:
    """Professional auth health checker with multi-probe strategy and caching.

    **Probe strategy (tried in order):**

    1. **Homepage** — fast, catches clear expiry (Google login redirect).
    2. **API** — creates a ``NotebookLMClient`` and lists notebooks.
       Only attempted when the homepage probe returns a redirect to
       Google login or an ``http_401``/``http_403``.  This accounts for
       the fact that the homepage and the RPC API endpoint may treat
       the same cookies differently.

    **Caching:**

    Results are cached for 30 seconds (``CACHE_TTL``).  The cache is
    bypassed on the next ``check()`` call if any auth file on disk
    has changed (detected via ``get_active_auth_mtime()``), so an
    external ``nlm login`` is picked up without waiting for the TTL
    to expire.

    **Diagnostics:**

    Every check returns an ``AuthHealthReport`` with per-probe details
    (endpoint, status code, latency, error) so callers can render
    a meaningful diagnostic message instead of a cryptic status label.
    """

    CACHE_TTL: float = 30.0

    def __init__(self, profile: str | None = None) -> None:
        self._profile = profile
        self._report: AuthHealthReport | None = None
        self._cache_ts: float = 0.0
        self._auth_mtime: float = 0.0
        self._auth_state: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, *, force: bool = False, timeout: float = 12.0) -> AuthHealthReport:
        """Return a cached or fresh health report.

        Args:
            force: If True, bypass the cache and run all probes.
            timeout: Timeout in seconds for each HTTP probe.

        Returns:
            An ``AuthHealthReport`` with the final verdict and per-probe details.
        """
        now = time.time()

        if not force and self._report is not None:
            age = now - self._cache_ts
            if age < self.CACHE_TTL:
                current_state = get_active_auth_state(self._profile)
                if current_state == self._auth_state:
                    return replace(self._report, cached=True)

        report = self._run_checks(timeout=timeout)

        self._report = report
        self._cache_ts = now
        self._auth_state = get_active_auth_state(self._profile)
        self._auth_mtime = get_active_auth_mtime()
        return report

    def invalidate(self) -> None:
        """Force the next ``check()`` call to re-run all probes."""
        self._report = None
        self._cache_ts = 0.0
        self._auth_state = None
        self._auth_mtime = 0.0

    # ------------------------------------------------------------------
    # Probe orchestration
    # ------------------------------------------------------------------

    def _run_checks(self, *, timeout: float = 12.0) -> AuthHealthReport:
        probes: list[AuthProbeResult] = []

        # Phase 1: Resolve the auth profile
        resolved_profile = self._profile
        if resolved_profile is None:
            from notebooklm_tools.utils.config import get_config

            resolved_profile = get_config().auth.default_profile

        # Resolved lazily so tests that monkeypatch
        # `notebooklm_tools.core.auth.AuthManager` are observed here.
        from notebooklm_tools.core.auth import AuthManager

        manager = AuthManager(resolved_profile)

        if not manager.profile_exists():
            return AuthHealthReport(
                valid=False,
                status="not_configured",
                probes=[],
                profile=resolved_profile,
                checked_at=time.time(),
            )

        try:
            profile = manager.load_profile()
            cookie_dict = self._cookies_to_dict(profile)
        except Exception as e:
            return AuthHealthReport(
                valid=False,
                status="stale",
                probes=[AuthProbeResult(probe="load", valid=False, error=str(e))],
                profile=resolved_profile,
                checked_at=time.time(),
            )

        if not cookie_dict:
            return AuthHealthReport(
                valid=False,
                status="not_configured",
                probes=[],
                profile=resolved_profile,
                checked_at=time.time(),
            )

        token_age = self._compute_token_age(profile)

        # Phase 2: Probe 1 — homepage fetch
        hp_start = time.perf_counter()
        hp_valid, hp_reason, hp_detail, hp_code = self._probe_homepage(cookie_dict, timeout=timeout)
        hp_latency = (time.perf_counter() - hp_start) * 1000

        if hp_reason is None:  # homepage succeeded
            probes.append(
                AuthProbeResult(
                    probe="homepage",
                    valid=True,
                    status_code=hp_code,
                    latency_ms=hp_latency,
                )
            )
            self._update_profile_on_success(manager, profile, hp_detail)
            return AuthHealthReport(
                valid=True,
                status="configured",
                probes=probes,
                token_age_hours=token_age,
                profile=resolved_profile,
                checked_at=time.time(),
            )

        probes.append(
            AuthProbeResult(
                probe="homepage",
                valid=False,
                status_code=hp_code,
                latency_ms=hp_latency,
                error=hp_reason,
                detail=hp_detail,
            )
        )

        # Phase 3: Probe 2 — lightweight API call (only when homepage redirects
        # to login or rejects auth, which is the most common false-positive scenario)
        if hp_reason in ("expired", "http_401", "http_403"):
            api_start = time.perf_counter()
            api_valid, api_error = self._probe_api(
                profile.cookies,
                profile.csrf_token,
                timeout=timeout,
                session_id=getattr(profile, "session_id", None),
                build_label=getattr(profile, "build_label", None),
                base_host=getattr(profile, "base_host", None),
                profile_name=resolved_profile,
            )
            api_latency = (time.perf_counter() - api_start) * 1000

            if api_valid:
                probes.append(
                    AuthProbeResult(
                        probe="api",
                        valid=True,
                        latency_ms=api_latency,
                        detail="Homepage rejected auth but API succeeded (false positive avoided).",
                    )
                )
                self._update_profile_on_success(manager, profile)
                return AuthHealthReport(
                    valid=True,
                    status="configured",
                    probes=probes,
                    token_age_hours=token_age,
                    profile=resolved_profile,
                    checked_at=time.time(),
                )

            probes.append(
                AuthProbeResult(
                    probe="api",
                    valid=False,
                    error=api_error or "unknown",
                    latency_ms=api_latency,
                )
            )

        # Phase 4: Determine final verdict from all probe results.
        # `valid` means "is the verdict the happy path?" — the same axis as `status`,
        # kept as a separate field for callers that only want a boolean.
        verdict = self._determine_verdict(probes)
        return AuthHealthReport(
            valid=verdict == "configured",
            status=verdict,
            probes=probes,
            token_age_hours=token_age,
            profile=resolved_profile,
            checked_at=time.time(),
        )

    # ------------------------------------------------------------------
    # Individual probes
    # ------------------------------------------------------------------

    def _probe_homepage(
        self, cookie_dict: dict[str, str], *, timeout: float
    ) -> tuple[bool, str | None, str | None, int | None]:
        """Fetch the NotebookLM homepage.

        Returns (valid, reason, detail, status_code).
        reason is None when the homepage check passes.
        """
        try:
            resp = _core_auth._fetch_notebooklm_homepage(cookie_dict, timeout=timeout)
            final_url = str(resp.url)

            if "accounts.google.com" in final_url:
                return False, "expired", final_url, resp.status_code
            if resp.status_code != 200:
                return False, f"http_{resp.status_code}", None, resp.status_code

            csrf = _core_auth.extract_csrf_from_page_source(resp.text) or ""
            if not csrf:
                return False, "expired", final_url, resp.status_code
            return True, None, csrf, resp.status_code

        except Exception as e:
            return False, f"network_error: {type(e).__name__}", str(e), None

    def _probe_api(
        self,
        cookies: dict[str, str] | list[dict[str, str]],
        csrf_token: str | None,
        *,
        timeout: float,
        session_id: str | None = None,
        build_label: str | None = None,
        base_host: str | None = None,
        profile_name: str | None = None,
    ) -> tuple[bool, str | None]:
        """Lightweight API probe: create a NotebookLMClient and list notebooks.

        Returns (valid, error_message_or_None).

        This is only called as a fallback when the homepage check looks
        expired.  The API endpoint often accepts cookies that the homepage
        rejects due to missing request headers.

        Transport errors (timeouts, connection refused, DNS) are reported
        with the ``"network_error:"`` prefix so that ``_determine_verdict``
        can distinguish them from genuine auth rejections.
        """
        try:
            from notebooklm_tools.core.client import NotebookLMClient

            with NotebookLMClient(
                cookies=cookies,
                csrf_token=csrf_token or "",
                session_id=session_id or "",
                build_label=build_label or "",
                base_host=base_host or "",
                profile_name=profile_name,
            ) as client:
                client.list_notebooks()
            return True, None
        except Exception as e:
            import httpx as _httpx

            if isinstance(e, (_httpx.TimeoutException, _httpx.RequestError)):
                # Transport-level failure: timeout, connection refused, DNS, etc.
                # These are not auth failures — they are "we don't know".
                return False, f"network_error: {type(e).__name__}: {e}"
            # Anything else (auth rejected, server error, unexpected) is
            # treated as a credential problem.
            return False, f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cookies_to_dict(profile: Any) -> dict[str, str]:
        """Convert profile cookies to a plain dict."""
        from notebooklm_tools.utils.browser import flatten_cookies

        if isinstance(profile.cookies, (dict, list)):
            return flatten_cookies(profile.cookies)
        return {}

    @staticmethod
    def _compute_token_age(profile: Any) -> float | None:
        """Return token age in hours, or None if unknown."""
        if profile.last_validated is None:
            return None
        try:
            return float((time.time() - profile.last_validated.timestamp()) / 3600)
        except Exception:
            return None

    @staticmethod
    def _update_profile_on_success(
        manager: Any, profile: Any, csrf_token: str | None = None
    ) -> None:
        """Persist fresh CSRF and update last_validated after a successful check.

        ``manager`` is typed as ``Any`` rather than ``AuthManager`` because
        ruff's name resolution does not honor ``from __future__ import
        annotations`` and the class is re-exported lazily through the
        services shim; the actual call site uses ``AuthManager`` from
        ``notebooklm_tools.core.auth`` at runtime.
        """
        try:
            manager.save_profile(
                cookies=profile.cookies,
                csrf_token=csrf_token or profile.csrf_token,
                session_id=profile.session_id,
                email=profile.email,
                build_label=profile.build_label,
                base_host=profile.base_host,
            )
        except Exception as e:
            logger.debug(f"Failed to update profile on successful auth check: {e}")

    @staticmethod
    def _determine_verdict(probes: list[AuthProbeResult]) -> str:
        """Aggregate probe results into a final verdict.

        Prioritisation:
        - No probes → ``"not_configured"`` (caller never set up auth).
        - All probes failed with transport errors → ``"unverified"``
          (we genuinely don't know — could be the user's Wi-Fi).
        - Any probe raised a non-transport error → ``"stale"``
          (auth was rejected by at least one endpoint).
        - Mixed (some transport, some auth) → ``"unverified"``
          (the auth-rejection could be a side effect of the transport
          failure; do not block the user from trying again).
        - Fallback (probes with no error string at all — internal
          inconsistency) → ``"stale"`` so the user is prompted to refresh.
        """
        if not probes:
            return "not_configured"

        has_auth_failure = any(p.error and not p.error.startswith("network_error:") for p in probes)
        has_network_error = any(p.error and p.error.startswith("network_error:") for p in probes)
        all_network_errors = all(p.error and p.error.startswith("network_error:") for p in probes)

        if all_network_errors:
            return "unverified"
        if has_auth_failure and not has_network_error:
            return "stale"
        if has_auth_failure and has_network_error:
            return "unverified"
        if has_network_error:
            return "unverified"
        return "stale"


# ---------------------------------------------------------------------------
# Process-wide singleton so the CLI and MCP share the same 30s cache
# ---------------------------------------------------------------------------


_notebook_count_cache: dict[str | None, tuple[float, int]] = {}
_count_cache_lock = threading.Lock()
_COUNT_CACHE_TTL = 10.0  # seconds


def _record_confirmed_notebook_count(profile: str | None, count: int) -> None:
    if not isinstance(profile, str) or not profile.strip():
        return
    now = time.monotonic()
    key = profile.strip()
    with _count_cache_lock:
        _notebook_count_cache[key] = (now, count)


def _get_confirmed_notebook_count(profile: str | None) -> int | None:
    if not isinstance(profile, str) or not profile.strip():
        return None
    now = time.monotonic()
    key = profile.strip()
    with _count_cache_lock:
        entry = _notebook_count_cache.get(key)
        if entry is not None:
            ts, count = entry
            if now - ts <= _COUNT_CACHE_TTL:
                return count
            del _notebook_count_cache[key]
    return None


def get_notebook_count(profile: Any) -> int | None:
    """Return a best-effort count without hiding an API authentication rejection."""
    profile_name = getattr(profile, "name", None)
    cached = _get_confirmed_notebook_count(profile_name)
    if cached is not None:
        return cached

    from notebooklm_tools.core.client import NotebookLMClient
    from notebooklm_tools.core.errors import ClientAuthenticationError
    from notebooklm_tools.core.exceptions import AuthenticationError
    from notebooklm_tools.services.errors import ServiceError

    try:
        with NotebookLMClient(
            cookies=profile.cookies,
            csrf_token=profile.csrf_token or "",
            session_id=profile.session_id or "",
            build_label=profile.build_label or "",
            base_host=profile.base_host or "",
            profile_name=profile_name,
        ) as client:
            count = len(client.list_notebooks())
            _record_confirmed_notebook_count(profile_name, count)
            return count
    except (AuthenticationError, ClientAuthenticationError) as exc:
        raise ServiceError("Credentials have expired.", category="authentication") from exc
    except Exception:
        return None


def confirm_auth_via_api(profile: str | None = None) -> tuple[bool, str | None]:
    """Confirm credentials with a live NotebookLM API call.

    Uses the same client parameters as ``nlm login --check`` (full cookie
    list plus session fields), not a flattened cookie dict.
    """
    if profile is None:
        from notebooklm_tools.utils.config import get_config

        profile = get_config().auth.default_profile

    from notebooklm_tools.core.auth import AuthManager
    from notebooklm_tools.core.client import NotebookLMClient
    from notebooklm_tools.core.errors import (
        ClientAuthenticationError,
        RPCError,
        TransientBackendError,
    )
    from notebooklm_tools.core.exceptions import AuthenticationError

    manager = AuthManager(profile)
    if not manager.profile_exists():
        return False, "not_configured"

    try:
        p = manager.load_profile()
        with NotebookLMClient(
            cookies=p.cookies,
            csrf_token=p.csrf_token or "",
            session_id=p.session_id or "",
            build_label=p.build_label or "",
            base_host=p.base_host or "",
            profile_name=profile,
        ) as client:
            notebooks = client.list_notebooks()
            _record_confirmed_notebook_count(profile, len(notebooks))
        return True, None
    except (ClientAuthenticationError, AuthenticationError) as exc:
        return False, f"auth_expired: {type(exc).__name__}: {exc}"
    except RPCError as exc:
        if exc.error_code in (7, 16):
            return False, f"auth_expired: RPCError({exc.error_code}): {exc}"
        return False, f"network_error: RPCError({exc.error_code}): {exc}"
    except TransientBackendError as exc:
        return False, f"network_error: TransientBackendError: {exc}"
    except Exception as exc:
        import httpx as _httpx

        if isinstance(exc, _httpx.HTTPStatusError):
            if exc.response.status_code in (401, 403):
                return False, f"auth_expired: HTTPStatusError: {exc.response.status_code}"
            return False, f"network_error: HTTPStatusError: {exc.response.status_code}"
        if isinstance(exc, (_httpx.TimeoutException, _httpx.RequestError)):
            return False, f"network_error: {type(exc).__name__}: {exc}"
        return False, f"network_error: {type(exc).__name__}: {exc}"


def _is_auth_rejection(err: str | None) -> bool:
    if not err:
        return False
    if err.startswith("network_error:"):
        return False
    lower = err.lower()
    return (
        lower.startswith("auth_expired:")
        or "clientauthenticationerror" in lower
        or "authenticationerror" in lower
        or "expired" in lower
        or "unauthenticated" in lower
        or "permission_denied" in lower
        or "401" in lower
        or "403" in lower
    )


def credentials_are_usable(
    *,
    force: bool = False,
    profile: str | None = None,
) -> tuple[bool, str, str | None]:
    """Return whether NotebookLM credentials can perform API operations.

    Runs ``AuthHealthChecker`` first, then falls back to a direct API probe
    when probes report ``stale`` or ``unverified`` — the semi-stale case
    where the homepage rejects cookies but RPC calls still work (#224).
    """
    report = get_auth_health_checker(profile=profile).check(force=force)
    if report.status == "configured":
        if not force:
            return True, report.status, None
        ok, err = confirm_auth_via_api(profile=report.profile)
        if ok:
            return True, "configured", None
        status = "stale" if _is_auth_rejection(err) else "unverified"
        return False, status, err

    if report.status in ("stale", "unverified"):
        ok, err = confirm_auth_via_api(profile=report.profile)
        if ok:
            return True, "configured", None
        status = "stale" if _is_auth_rejection(err) else "unverified"
        return False, status, err

    detail = next((p.error for p in report.probes if p.error), None)
    return False, report.status, detail


_checkers: dict[str | None, AuthHealthChecker] = {}
_checker_lock = threading.Lock()


def get_auth_health_checker(profile: str | None = None) -> AuthHealthChecker:
    """Return the cached AuthHealthChecker for one auth profile.

    Calls that omit ``profile`` retain the historical shared checker for the
    configured default profile. Explicit profile names receive independent
    cached health state so one process can validate multiple saved accounts
    without switching global configuration.
    """
    key = profile.strip() if isinstance(profile, str) and profile.strip() else None
    checker = _checkers.get(key)
    if checker is None:
        with _checker_lock:
            checker = _checkers.get(key)
            if checker is None:
                checker = AuthHealthChecker(profile=key)
                _checkers[key] = checker
    return checker
