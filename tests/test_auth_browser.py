"""Tests for supported authentication browser behavior."""

import json
from pathlib import Path
from unittest.mock import patch


def test_select_auth_backend_uses_firefox_when_explicitly_requested():
    from notebooklm_tools.utils.auth_browser import select_auth_backend

    with (
        patch("notebooklm_tools.utils.cdp._get_chromium_path", return_value="chromium"),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value="firefox"),
    ):
        backend = select_auth_backend("firefox")

    assert backend == {"backend": "firefox_profile", "browser": "Firefox"}


def test_select_auth_backend_auto_prefers_chromium_when_available():
    from notebooklm_tools.utils.auth_browser import select_auth_backend

    with (
        patch("notebooklm_tools.utils.cdp._get_chromium_path", return_value="google-chrome"),
        patch("notebooklm_tools.utils.cdp.get_browser_display_name", return_value="Google Chrome"),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value="firefox"),
    ):
        backend = select_auth_backend("auto")

    assert backend == {"backend": "chromium_cdp", "browser": "Google Chrome"}


def test_select_auth_backend_auto_uses_firefox_when_chromium_is_unavailable():
    from notebooklm_tools.utils.auth_browser import select_auth_backend

    with (
        patch("notebooklm_tools.utils.cdp._get_chromium_path", return_value=None),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value="firefox"),
    ):
        backend = select_auth_backend("auto")

    assert backend == {"backend": "firefox_profile", "browser": "Firefox"}


def test_supported_auth_browsers_includes_firefox_when_installed():
    from notebooklm_tools.utils.auth_browser import get_supported_auth_browsers

    with (
        patch(
            "notebooklm_tools.utils.cdp.get_supported_browsers",
            return_value=["Google Chrome", "Chromium"],
        ),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value="firefox"),
    ):
        browsers = get_supported_auth_browsers()

    assert browsers == ["Google Chrome", "Chromium", "Firefox"]


def test_get_chromium_path_ignores_explicit_firefox_preference():
    from notebooklm_tools.utils.cdp import _get_chromium_path

    assert _get_chromium_path("firefox") is None


def test_select_auth_backend_passes_comet_preference_to_chromium_discovery():
    from notebooklm_tools.utils.auth_browser import select_auth_backend

    with (
        patch(
            "notebooklm_tools.utils.cdp._get_chromium_path",
            return_value="/Applications/Comet.app/Contents/MacOS/Comet",
        ) as get_path,
        patch("notebooklm_tools.utils.cdp.get_browser_display_name", return_value="Comet"),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value=None),
    ):
        backend = select_auth_backend("comet")

    assert backend == {"backend": "chromium_cdp", "browser": "Comet"}
    get_path.assert_called_once_with("comet")


def test_get_chromium_path_selects_named_comet_on_macos():
    from notebooklm_tools.utils.cdp import _get_chromium_path

    expected = str(Path("/Applications") / "Comet.app/Contents/MacOS/Comet")

    def fake_exists(path: Path) -> bool:
        return str(path) == expected

    with (
        patch("notebooklm_tools.utils.cdp.platform.system", return_value="Darwin"),
        patch.object(Path, "exists", fake_exists),
        patch(
            "notebooklm_tools.utils.cdp._get_preferred_browser_path",
            return_value="",
            create=True,
        ),
    ):
        result = _get_chromium_path("comet")

    assert result == expected


def test_edge_beta_is_a_supported_explicit_auth_browser():
    from notebooklm_tools.utils.auth_browser import CHROMIUM_BROWSER_KEYS

    assert "edge-beta" in CHROMIUM_BROWSER_KEYS


def test_select_auth_backend_passes_edge_beta_preference():
    from notebooklm_tools.utils.auth_browser import select_auth_backend

    with (
        patch(
            "notebooklm_tools.utils.cdp._get_chromium_path",
            return_value="msedge-beta",
        ) as get_path,
        patch(
            "notebooklm_tools.utils.cdp.get_browser_display_name",
            return_value="Microsoft Edge Beta",
        ),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value=None),
    ):
        backend = select_auth_backend("edge-beta")

    get_path.assert_called_once_with("edge-beta")
    assert backend == {"backend": "chromium_cdp", "browser": "Microsoft Edge Beta"}


def test_get_chromium_path_selects_edge_beta_candidate(tmp_path, monkeypatch):
    from notebooklm_tools.utils import cdp

    beta = tmp_path / "msedge.exe"
    beta.write_bytes(b"")
    monkeypatch.setattr(cdp.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        cdp,
        "_windows_browser_candidates",
        lambda: [
            ("Google Chrome", str(tmp_path / "missing-chrome.exe")),
            ("Microsoft Edge Beta", str(beta)),
        ],
    )
    monkeypatch.setattr(cdp, "_detected_browser_name", None)
    monkeypatch.setattr(cdp, "_get_preferred_browser_path", lambda: "")

    assert cdp._get_chromium_path("edge-beta") == str(beta)
    assert cdp.get_browser_display_name() == "Microsoft Edge Beta"


def test_platform_candidates_include_edge_beta():
    from notebooklm_tools.utils.cdp import (
        _LINUX_BROWSER_CANDIDATES,
        _macos_browser_candidates,
        _windows_browser_candidates,
    )

    assert ("Microsoft Edge Beta", "microsoft-edge-beta") in _LINUX_BROWSER_CANDIDATES
    assert any(name == "Microsoft Edge Beta" for name, _ in _macos_browser_candidates())

    beta_paths = [
        path for name, path in _windows_browser_candidates() if name == "Microsoft Edge Beta"
    ]
    assert beta_paths
    assert any(r"Microsoft\Edge Beta\Application\msedge.exe" in path for path in beta_paths)


def test_explicit_browser_path_wins_over_named_discovery(tmp_path):
    from notebooklm_tools.utils.cdp import _get_chromium_path

    executable = tmp_path / "future-browser"
    executable.write_text("browser", encoding="utf-8")
    executable.chmod(0o755)

    with (
        patch("notebooklm_tools.utils.cdp.platform.system", return_value="Linux"),
        patch("notebooklm_tools.utils.cdp.shutil.which", return_value="/usr/bin/google-chrome"),
        patch(
            "notebooklm_tools.utils.cdp._get_preferred_browser_path",
            return_value=str(executable),
            create=True,
        ),
    ):
        result = _get_chromium_path("chrome")

    assert result == str(executable)


def test_invalid_explicit_browser_path_does_not_fall_back(tmp_path):
    from notebooklm_tools.utils.cdp import _get_chromium_path

    missing = tmp_path / "missing-browser"

    with (
        patch("notebooklm_tools.utils.cdp.platform.system", return_value="Linux"),
        patch("notebooklm_tools.utils.cdp.shutil.which", return_value="/usr/bin/google-chrome"),
        patch(
            "notebooklm_tools.utils.cdp._get_preferred_browser_path",
            return_value=str(missing),
            create=True,
        ),
    ):
        result = _get_chromium_path("chrome")

    assert result is None


def test_invalid_explicit_browser_path_suppresses_firefox_fallback():
    from notebooklm_tools.utils.auth_browser import select_auth_backend

    with (
        patch("notebooklm_tools.utils.cdp._get_chromium_path", return_value=None),
        patch(
            "notebooklm_tools.utils.cdp._get_preferred_browser_path",
            return_value="/missing/browser",
            create=True,
        ),
        patch("notebooklm_tools.utils.firefox.get_firefox_path", return_value="/usr/bin/firefox"),
    ):
        backend = select_auth_backend("auto")

    assert backend is None


def test_browser_path_environment_override_is_loaded(monkeypatch, tmp_path):
    from notebooklm_tools.utils.config import load_config

    config_file = tmp_path / "missing-config.toml"
    monkeypatch.setenv("NLM_BROWSER_PATH", "/opt/custom/chromium")

    with patch("notebooklm_tools.utils.config.get_config_file", return_value=config_file):
        config = load_config()

    assert config.auth.browser_path == "/opt/custom/chromium"


def test_browser_path_is_serialized_to_toml():
    from notebooklm_tools.utils.config import AuthConfig, Config, _config_to_toml

    config = Config(auth=AuthConfig(browser_path="/opt/custom/chromium"))

    assert 'browser_path = "/opt/custom/chromium"' in _config_to_toml(config)


def test_saved_legacy_browser_backend_is_read_from_metadata(tmp_path, monkeypatch):
    from notebooklm_tools.core.auth import AuthManager
    from notebooklm_tools.utils.auth_browser import _get_saved_browser_backend

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path))

    auth = AuthManager("default")
    auth.save_profile(cookies={"SID": "sid", "HSID": "hsid"}, email="user@example.com")

    metadata = json.loads(auth.metadata_file.read_text(encoding="utf-8"))
    metadata["browser_backend"] = "firefox_playwright"
    auth.metadata_file.write_text(json.dumps(metadata), encoding="utf-8")

    assert _get_saved_browser_backend("default") == "firefox_playwright"


def test_flatten_cookies_prefers_google_com_over_other_domains():
    from notebooklm_tools.utils.browser import flatten_cookies

    cookies = [
        {"name": "SID", "value": "youtube_sid", "domain": ".youtube.com"},
        {"name": "SID", "value": "google_sid", "domain": ".google.com"},
        {"name": "SID", "value": "vn_sid", "domain": ".google.com.vn"},
        {"name": "HSID", "value": "youtube_hsid", "domain": ".youtube.com"},
        {"name": "HSID", "value": "google_hsid", "domain": ".google.com"},
        {"name": "ONLY_VN", "value": "vn_only", "domain": ".google.com.vn"},
    ]

    flat = flatten_cookies(cookies)

    assert flat["SID"] == "google_sid"
    assert flat["HSID"] == "google_hsid"
    assert flat["ONLY_VN"] == "vn_only"


def test_flatten_cookies_passthrough_dict_and_skips_malformed():
    from notebooklm_tools.utils.browser import flatten_cookies

    assert flatten_cookies({"SID": "x"}) == {"SID": "x"}
    assert flatten_cookies([{"name": "SID"}, {"value": "no_name"}]) == {}


def test_flatten_cookies_empty_list_and_empty_value():
    from notebooklm_tools.utils.browser import flatten_cookies

    assert flatten_cookies([]) == {}
    assert flatten_cookies([{"name": "X", "value": ""}]) == {"X": ""}


def test_validate_cookies_accepts_chrome_list():
    from notebooklm_tools.core.auth import validate_cookies

    chrome_list = [
        {"name": n, "value": "v", "domain": ".google.com"}
        for n in ("SID", "HSID", "SSID", "APISID", "SAPISID")
    ]

    assert validate_cookies(chrome_list) is True
    assert validate_cookies(chrome_list[:2]) is False


def test_validate_notebooklm_cookies_accepts_chrome_list():
    from notebooklm_tools.utils.browser import validate_notebooklm_cookies

    chrome_list = [
        {"name": "SID", "value": "v", "domain": ".google.com"},
        {"name": "HSID", "value": "v", "domain": ".google.com"},
    ]

    assert validate_notebooklm_cookies(chrome_list) is True
    assert validate_notebooklm_cookies([]) is False


def test_auth_tokens_cookie_header_flattens_list():
    from notebooklm_tools.core.auth import AuthTokens

    tokens = AuthTokens(
        cookies=[
            {"name": "SID", "value": "vn", "domain": ".google.com.vn"},
            {"name": "SID", "value": "google", "domain": ".google.com"},
        ]
    )

    assert tokens.cookie_header == "SID=google"


def test_get_headers_flattens_list_cookies(tmp_path, monkeypatch):
    from notebooklm_tools.core.auth import AuthManager

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path))

    auth = AuthManager("default")
    auth.save_profile(
        cookies=[
            {"name": "SID", "value": "google", "domain": ".google.com"},
            {"name": "SID", "value": "youtube", "domain": ".youtube.com"},
        ],
        csrf_token="csrf1",
        email="u@example.com",
    )

    headers = auth.get_headers()

    assert "SID=google" in headers["Cookie"]
    assert "youtube" not in headers["Cookie"]
    assert headers["X-Goog-Csrf-Token"] == "csrf1"


def test_get_headers_uses_saved_base_host(tmp_path, monkeypatch):
    """Origin/Referer follow the host the account was signed in on (issue #332)."""
    from notebooklm_tools.core.auth import AuthManager

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path))
    monkeypatch.delenv("NOTEBOOKLM_BASE_URL", raising=False)

    auth = AuthManager("default")
    auth.save_profile(
        cookies=[{"name": "SID", "value": "google", "domain": ".google.com"}],
        csrf_token="csrf1",
        email="u@example.com",
        base_host="notebook.google.com",
    )

    headers = auth.get_headers()

    assert headers["Origin"] == "https://notebook.google.com"
    assert headers["Referer"] == "https://notebook.google.com/"


def test_get_headers_defaults_host_when_unset(tmp_path, monkeypatch):
    """No saved host falls back to the default (issue #332)."""
    from notebooklm_tools.core.auth import AuthManager

    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path))
    monkeypatch.delenv("NOTEBOOKLM_BASE_URL", raising=False)

    auth = AuthManager("default")
    auth.save_profile(
        cookies=[{"name": "SID", "value": "google", "domain": ".google.com"}],
        csrf_token="csrf1",
        email="u@example.com",
    )

    headers = auth.get_headers()

    assert headers["Origin"] == "https://notebooklm.google.com"
    assert headers["Referer"] == "https://notebooklm.google.com/"


def test_headless_auth_forwards_diagnostic_mode_to_chromium(monkeypatch):
    """Explicit refresh diagnostics must reach the Chromium backend."""
    from notebooklm_tools.utils import auth_browser, cdp

    calls = {}
    monkeypatch.setattr(
        auth_browser,
        "_get_saved_browser_backend",
        lambda _profile: "chromium_cdp",
    )
    monkeypatch.setattr(
        auth_browser,
        "select_auth_backend",
        lambda: {"backend": "chromium_cdp", "browser": "Google Chrome"},
    )

    def fake_headless(
        *,
        timeout,
        profile_name,
        expected_revision,
        force,
        raise_on_error,
    ):
        calls.update(
            profile_name=profile_name,
            raise_on_error=raise_on_error,
        )
        return None

    monkeypatch.setattr(cdp, "run_headless_auth", fake_headless)

    result = auth_browser.run_headless_auth(
        profile_name="work",
        raise_on_error=True,
    )

    assert result is None
    assert calls == {"profile_name": "work", "raise_on_error": True}


def test_headless_auth_diagnostic_mode_preserves_backend_fallback(monkeypatch):
    """A diagnostic failure in one backend must not block a later fallback."""
    from notebooklm_tools.core.exceptions import AuthenticationError
    from notebooklm_tools.utils import auth_browser, cdp, firefox

    token = object()
    calls = []
    monkeypatch.setattr(
        auth_browser,
        "_get_saved_browser_backend",
        lambda _profile: "firefox_profile",
    )
    monkeypatch.setattr(
        auth_browser,
        "select_auth_backend",
        lambda: {"backend": "firefox_profile", "browser": "Firefox"},
    )

    def fail_firefox(**kwargs):
        calls.append(("firefox", kwargs["raise_on_error"]))
        raise AuthenticationError(message="Firefox profile unavailable")

    def succeed_chromium(**kwargs):
        calls.append(("chromium", kwargs["raise_on_error"]))
        return token

    monkeypatch.setattr(firefox, "run_headless_auth", fail_firefox)
    monkeypatch.setattr(cdp, "run_headless_auth", succeed_chromium)

    result = auth_browser.run_headless_auth(
        profile_name="work",
        raise_on_error=True,
    )

    assert result is token
    assert calls == [("firefox", True), ("chromium", True)]


def test_headless_auth_diagnostic_mode_reports_preferred_backend_failure(monkeypatch):
    """A later fallback's failure must not hide the preferred backend's real error."""
    import pytest

    from notebooklm_tools.core.exceptions import AuthenticationError
    from notebooklm_tools.utils import auth_browser, cdp, firefox

    monkeypatch.setattr(auth_browser, "_get_saved_browser_backend", lambda _p: "firefox_profile")
    monkeypatch.setattr(
        auth_browser,
        "select_auth_backend",
        lambda: {"backend": "firefox_profile", "browser": "Firefox"},
    )

    def fail_firefox(**kwargs):
        raise AuthenticationError(message="Firefox signed out")

    def fail_chromium(**kwargs):
        raise AuthenticationError(message="No saved browser profile is available")

    monkeypatch.setattr(firefox, "run_headless_auth", fail_firefox)
    monkeypatch.setattr(cdp, "run_headless_auth", fail_chromium)

    with pytest.raises(AuthenticationError) as exc_info:
        auth_browser.run_headless_auth(profile_name="work", raise_on_error=True)

    assert exc_info.value.message == "Firefox signed out"


def test_firefox_headless_auth_raises_when_profile_missing_in_diagnostic_mode(monkeypatch):
    import pytest

    from notebooklm_tools.core.exceptions import AuthenticationError
    from notebooklm_tools.utils import firefox

    monkeypatch.setattr("notebooklm_tools.utils.config.get_auth_storage_mode", lambda _p: "file")
    monkeypatch.setattr(firefox, "has_firefox_profile", lambda _p: False)

    assert firefox.run_headless_auth(profile_name="work") is None
    with pytest.raises(AuthenticationError, match="No saved Firefox profile"):
        firefox.run_headless_auth(profile_name="work", raise_on_error=True)


def test_firefox_headless_auth_raises_when_cookies_invalid_in_diagnostic_mode(monkeypatch):
    import pytest

    from notebooklm_tools.core.exceptions import AuthenticationError
    from notebooklm_tools.utils import firefox

    monkeypatch.setattr("notebooklm_tools.utils.config.get_auth_storage_mode", lambda _p: "file")
    monkeypatch.setattr(firefox, "has_firefox_profile", lambda _p: True)
    monkeypatch.setattr(firefox, "get_firefox_profile_dir", lambda _p: Path("."))
    monkeypatch.setattr(firefox, "_read_google_cookies", lambda _d: [])
    monkeypatch.setattr("notebooklm_tools.core.auth.validate_cookies", lambda _c: False)

    assert firefox.run_headless_auth(profile_name="work") is None
    with pytest.raises(AuthenticationError, match="required NotebookLM cookies"):
        firefox.run_headless_auth(profile_name="work", raise_on_error=True)


def test_firefox_read_google_cookies_closes_sqlite_connections_and_releases_file(
    tmp_path, monkeypatch
):
    import shutil
    import sqlite3

    import pytest

    from notebooklm_tools.utils import firefox

    profile_dir = tmp_path / "firefox-profile"
    profile_dir.mkdir()
    cookie_db = profile_dir / "cookies.sqlite"
    seed = sqlite3.connect(cookie_db)
    try:
        seed.execute(
            "CREATE TABLE moz_cookies ("
            "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER, isHttpOnly INTEGER"
            ")"
        )
        seed.execute(
            "INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("SID", "sid-val", ".google.com", "/", 9999999999, 1, 1),
        )
        seed.execute(
            "INSERT INTO moz_cookies VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("OTHER", "other-val", ".example.com", "/", 9999999999, 1, 0),
        )
        seed.commit()
    finally:
        seed.close()

    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(firefox.sqlite3, "connect", tracking_connect)

    try:
        cookies = firefox._read_google_cookies(profile_dir)
        assert len(cookies) == 1
        assert cookies[0]["name"] == "SID"
        assert len(opened) == 2

        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                conn.execute("SELECT 1")

        # On Windows an unclosed handle to cookies.sqlite blocks profile cleanup.
        shutil.rmtree(profile_dir)
        assert not profile_dir.exists()
    finally:
        for conn in opened:
            conn.close()


def test_firefox_read_google_cookies_closes_sqlite_connections_on_error(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    from notebooklm_tools.utils import firefox

    profile_dir = tmp_path / "firefox-bad-db"
    profile_dir.mkdir()
    cookie_db = profile_dir / "cookies.sqlite"
    seed = sqlite3.connect(cookie_db)
    seed.close()

    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened.append(conn)
        return conn

    monkeypatch.setattr(firefox.sqlite3, "connect", tracking_connect)

    try:
        assert firefox._read_google_cookies(profile_dir) == []
        assert len(opened) == 2
        for conn in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                conn.execute("SELECT 1")
    finally:
        for conn in opened:
            conn.close()


def test_launch_firefox_uses_devnull_instead_of_unread_pipes(tmp_path, monkeypatch):
    import subprocess
    from unittest.mock import MagicMock

    from notebooklm_tools.utils import firefox

    popen_mock = MagicMock()
    monkeypatch.setattr(firefox.subprocess, "Popen", popen_mock)

    firefox._launch_firefox("/usr/bin/firefox", tmp_path)

    _, kwargs = popen_mock.call_args
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL


def test_terminate_firefox_process_reaps_after_kill():
    import subprocess
    from unittest.mock import MagicMock

    from notebooklm_tools.utils import firefox

    proc = MagicMock()
    proc.wait.side_effect = [subprocess.TimeoutExpired(cmd="firefox", timeout=5), 0]

    firefox._terminate_process(proc)

    proc.terminate.assert_called_once()
    proc.kill.assert_called_once()
    assert proc.wait.call_count == 2
