"""Tests for the services.auth re-export shim.

The shim exists to satisfy the layering rule (cli/ and mcp/ must not import
from core/); the real behavior lives in core.auth. These tests pin the
re-export contract so the shim does not silently drift.
"""

from notebooklm_tools.core import auth as core_auth
from notebooklm_tools.services import auth as services_auth


def test_shim_reexports_expected_auth_symbols():
    """The shim exposes the full set of auth symbols needed by cli/mcp:
    the four data/auth helpers (check_auth, load_cached_tokens,
    save_tokens_to_cache, get_cache_path, validate_cookies), the two
    class symbols re-exported from core (AuthTokens, AuthManager), the
    AuthHealthChecker family owned by this module, the auth replay diagnostic
    helpers, the mtime helper, and the singleton accessor.
    """
    assert sorted(services_auth.__all__) == sorted(
        [
            "AuthHealthChecker",
            "AuthHealthReport",
            "AuthManager",
            "AuthProbeResult",
            "AuthReplayDiagnostic",
            "AuthReplayProbe",
            "AuthTokens",
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
    )


def test_shim_check_auth_forwards_to_core_implementation(monkeypatch):
    """`services.auth.check_auth(...)` must delegate to
    `notebooklm_tools.core.auth.check_auth`. Verified by patching the core
    function and confirming the shim picks up the patch (i.e. it does not
    capture the original function at import time).
    """
    sentinel_result = object()

    def _fake_check_auth(*args, **kwargs):
        return sentinel_result

    monkeypatch.setattr(core_auth, "check_auth", _fake_check_auth, raising=True)
    # The wrapper resolves lazily on each call, so a patch to core.check_auth
    # is observed by the shim.
    assert services_auth.check_auth(live=True) is sentinel_result


def test_shim_check_auth_passes_args_and_kwargs_through(monkeypatch):
    """Args and kwargs must be forwarded unchanged to the core implementation."""
    captured = {}

    def _capturing_check_auth(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "ok"

    monkeypatch.setattr(core_auth, "check_auth", _capturing_check_auth, raising=True)
    services_auth.check_auth("positional", live=True, timeout=5)
    assert captured["args"] == ("positional",)
    assert captured["kwargs"] == {"live": True, "timeout": 5}


def test_shim_load_cached_tokens_forwards_to_core(monkeypatch):
    """`load_cached_tokens` wrapper must call the core implementation and
    return its result.
    """
    sentinel = object()

    def _fake_load():
        return sentinel

    monkeypatch.setattr(core_auth, "load_cached_tokens", _fake_load, raising=True)
    assert services_auth.load_cached_tokens() is sentinel


def test_shim_save_tokens_to_cache_forwards_kwargs(monkeypatch):
    """`save_tokens_to_cache` wrapper must forward (tokens, silent=...) to
    the core implementation.
    """
    captured = {}

    def _fake_save(tokens, silent=False):
        captured["tokens"] = tokens
        captured["silent"] = silent

    sentinel_tokens = object()
    monkeypatch.setattr(core_auth, "save_tokens_to_cache", _fake_save, raising=True)
    services_auth.save_tokens_to_cache(sentinel_tokens, silent=True)
    assert captured == {"tokens": sentinel_tokens, "silent": True}


def test_shim_auth_cache_helpers_forward_explicit_profile(monkeypatch):
    captured = {}

    def _fake_load(*, profile_name):
        captured["loaded"] = profile_name
        return "tokens"

    def _fake_save(tokens, silent=False, profile_name=None):
        captured["saved"] = (tokens, silent, profile_name)

    monkeypatch.setattr(core_auth, "load_cached_tokens", _fake_load, raising=True)
    monkeypatch.setattr(core_auth, "save_tokens_to_cache", _fake_save, raising=True)

    assert services_auth.load_cached_tokens("tsm") == "tokens"
    services_auth.save_tokens_to_cache("tokens", silent=True, profile_name="tsm")
    assert captured == {"loaded": "tsm", "saved": ("tokens", True, "tsm")}


def test_shim_validate_cookies_forwards_to_core(monkeypatch):
    """`validate_cookies` wrapper must forward the cookies dict and return
    the core result.
    """
    captured = {}

    def _fake_validate(cookies):
        captured["cookies"] = cookies
        return "ok"

    monkeypatch.setattr(core_auth, "validate_cookies", _fake_validate, raising=True)
    result = services_auth.validate_cookies({"SID": "sid"})
    assert result == "ok"
    assert captured == {"cookies": {"SID": "sid"}}


def test_shim_auth_manager_resolves_to_current_core_class(monkeypatch):
    """`services.auth.AuthManager` must resolve to the CURRENT
    `core.auth.AuthManager`, not a snapshot taken at import time. Verified
    by patching core.auth.AuthManager with a sentinel class and confirming
    the shim's PEP 562 `__getattr__` returns the patched class on access.
    """
    sentinel_class = type("SentinelAuthManager", (), {})

    monkeypatch.setattr(core_auth, "AuthManager", sentinel_class, raising=True)
    assert services_auth.AuthManager is sentinel_class


def test_shim_auth_tokens_resolves_to_current_core_class(monkeypatch):
    """`services.auth.AuthTokens` must resolve to the current
    `core.auth.AuthTokens` on every access (no caching).
    """
    sentinel_class = type("SentinelAuthTokens", (), {})

    monkeypatch.setattr(core_auth, "AuthTokens", sentinel_class, raising=True)
    assert services_auth.AuthTokens is sentinel_class


def test_shim_class_resolution_works_through_from_import(monkeypatch):
    """The pattern `from notebooklm_tools.services.auth import AuthManager`
    inside a function body must pick up a monkeypatched core.auth.AuthManager,
    just like the inline import pattern. This pins the contract that
    downstream code (cli/main.py, etc.) relies on.
    """
    sentinel_class = type("FromImportSentinel", (), {})

    monkeypatch.setattr(core_auth, "AuthManager", sentinel_class, raising=True)
    # Re-execute the import statement the same way cli code does.
    local_namespace = {}
    exec("from notebooklm_tools.services.auth import AuthManager", local_namespace)
    assert local_namespace["AuthManager"] is sentinel_class


def test_shim_class_resolution_does_not_cache_across_patches(monkeypatch):
    """Caching PEP 562 lookups in module globals would poison the shim
    for any caller that imports early (e.g. cli/utils.py:13) and then
    runs a test that monkeypatches core.auth.AuthManager. This test
    pins the no-cache contract by patching twice and confirming both
    patches are observed.
    """
    first_class = type("FirstSentinel", (), {})
    second_class = type("SecondSentinel", (), {})

    monkeypatch.setattr(core_auth, "AuthManager", first_class, raising=True)
    assert services_auth.AuthManager is first_class
    monkeypatch.setattr(core_auth, "AuthManager", second_class, raising=True)
    assert services_auth.AuthManager is second_class, (
        "PEP 562 lookup must re-resolve on every access; a cache would "
        "leak the first patched class into the second access."
    )


# --------------------------------------------------------------------------- #
# get_active_auth_mtime — guards the auth-guard mtime check against the
# real auth-file layout (modern multi-profile vs. legacy single-file).
#
# Note: the helper stats ALL `cookies.json` files under `profiles/`, not
# just the config-default profile's, so an external `nlm login --profile
# <other>` correctly invalidates the guard even if it doesn't match the
# config's `default_profile`. Live-testing caught the narrower version of
# this bug in v0.6.15 prep.
# --------------------------------------------------------------------------- #
def test_get_active_auth_mtime_reads_any_profile_cookies(monkeypatch, tmp_path):
    """The helper must stat every `cookies.json` under `profiles/`, not
    just the one for the config-default profile. A write to ANY profile's
    file invalidates the guard.
    """
    import time as _time

    profiles_dir = tmp_path / "profiles"
    personal_dir = profiles_dir / "personal"
    personal_dir.mkdir(parents=True)
    personal_cookies = personal_dir / "cookies.json"
    personal_cookies.write_text("{}")
    personal_mtime = personal_cookies.stat().st_mtime

    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_profiles_dir",
        lambda: profiles_dir,
        raising=True,
    )
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_storage_dir",
        lambda: tmp_path,
        raising=True,
    )

    assert services_auth.get_active_auth_mtime() == personal_mtime

    # Touch a different profile's cookies.json. Result must follow.
    _time.sleep(0.02)
    work_dir = profiles_dir / "work"
    work_dir.mkdir()
    work_cookies = work_dir / "cookies.json"
    work_cookies.write_text("{}")
    work_mtime = work_cookies.stat().st_mtime
    assert work_mtime > personal_mtime
    assert services_auth.get_active_auth_mtime() == work_mtime


def test_get_active_auth_mtime_falls_back_to_legacy_auth_json(monkeypatch, tmp_path):
    """Legacy users have auth in `<storage>/auth.json` and no profile
    cookies.json. The mtime helper must still return the legacy file's
    mtime in that case.
    """
    profiles_dir = tmp_path / "profiles" / "default"
    profiles_dir.mkdir(parents=True)
    # No cookies.json inside — modern path is absent.

    legacy_file = tmp_path / "auth.json"
    legacy_file.write_text("{}")
    expected_mtime = legacy_file.stat().st_mtime

    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_profiles_dir",
        lambda: tmp_path / "profiles",
        raising=True,
    )
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_storage_dir",
        lambda: tmp_path,
        raising=True,
    )

    assert services_auth.get_active_auth_mtime() == expected_mtime


def test_get_active_auth_mtime_returns_max_across_profiles_and_legacy(monkeypatch, tmp_path):
    """Across N profile cookies.json files plus the legacy auth.json, the
    helper must return the maximum mtime. This pins the contract that a
    write to any single file invalidates the guard.
    """
    import time as _time

    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "personal").mkdir(parents=True)
    (profiles_dir / "work").mkdir()
    personal_cookies = profiles_dir / "personal" / "cookies.json"
    work_cookies = profiles_dir / "work" / "cookies.json"
    legacy_file = tmp_path / "auth.json"
    personal_cookies.write_text("{}")
    work_cookies.write_text("{}")
    legacy_file.write_text("{}")

    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_profiles_dir",
        lambda: profiles_dir,
        raising=True,
    )
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_storage_dir",
        lambda: tmp_path,
        raising=True,
    )

    # The max of all three.
    expected = max(
        personal_cookies.stat().st_mtime,
        work_cookies.stat().st_mtime,
        legacy_file.stat().st_mtime,
    )
    assert services_auth.get_active_auth_mtime() == expected

    # Touch personal cookies; result must follow.
    _time.sleep(0.02)
    personal_cookies.touch()
    assert services_auth.get_active_auth_mtime() == personal_cookies.stat().st_mtime


def test_get_active_auth_mtime_returns_zero_when_no_files(monkeypatch, tmp_path):
    """Fresh install with no auth file at all must return 0.0 (sentinel for
    'no cache yet'), not raise.
    """
    empty_profiles = tmp_path / "profiles"
    empty_profiles.mkdir()

    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_profiles_dir",
        lambda: empty_profiles,
        raising=True,
    )
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_storage_dir",
        lambda: tmp_path,
        raising=True,
    )

    assert services_auth.get_active_auth_mtime() == 0.0


def test_get_active_auth_mtime_survives_missing_profiles_dir(monkeypatch, tmp_path):
    """If the profiles directory does not exist (rare; pre-migration or
    wiped install), the helper must still return the legacy auth.json
    mtime, not raise.
    """
    legacy_file = tmp_path / "auth.json"
    legacy_file.write_text("{}")
    expected_mtime = legacy_file.stat().st_mtime

    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_profiles_dir",
        lambda: tmp_path / "profiles",  # does not exist
        raising=True,
    )
    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_storage_dir",
        lambda: tmp_path,
        raising=True,
    )

    assert services_auth.get_active_auth_mtime() == expected_mtime


def test_get_active_auth_mtime_swallows_exceptions(monkeypatch):
    """If config loading blows up (corrupt config, missing dir perms, etc.)
    the helper must return 0.0 instead of propagating. A wrong mtime answer
    is far less harmful than a 500 on `studio_create` for an unrelated
    config error.
    """

    def _explode():
        raise RuntimeError("config corrupted")

    monkeypatch.setattr(
        "notebooklm_tools.utils.config.get_storage_dir",
        _explode,
        raising=True,
    )

    assert services_auth.get_active_auth_mtime() == 0.0
