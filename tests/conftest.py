import fnmatch
import os
from pathlib import Path

import pytest


def _is_allowed_live_modification(rel_path: str) -> bool:
    """Check if a modified file in ~/.notebooklm-mcp-cli is on the live-written allowlist."""
    norm = rel_path.replace("\\", "/")
    if norm in ("auth.json", "update_check.json", "cache/update_check.json"):
        return True
    if fnmatch.fnmatch(norm, "profiles/*/cookies.json"):
        return True
    return bool(fnmatch.fnmatch(norm, "profiles/*/metadata.json"))


StorageFingerprint = tuple[int, int]


def _snapshot_storage_dir(dir_path: Path) -> dict[str, StorageFingerprint]:
    """Record path fingerprints as (mtime_ns, size), never file contents."""
    snapshot: dict[str, StorageFingerprint] = {}
    if not dir_path.exists():
        return snapshot
    for root, dirs, files in os.walk(dir_path):
        dirs[:] = [d for d in dirs if not d.startswith("chrome-profile")]
        for f in files:
            p = Path(root) / f
            try:
                rel = p.relative_to(dir_path).as_posix()
                stat_result = p.stat()
                snapshot[rel] = (stat_result.st_mtime_ns, stat_result.st_size)
            except (OSError, ValueError):
                pass
    return snapshot


def _check_tripwire_changes(
    before_mcp_cli: dict[str, StorageFingerprint],
    after_mcp_cli: dict[str, StorageFingerprint],
    before_mcp: dict[str, StorageFingerprint],
    after_mcp: dict[str, StorageFingerprint],
) -> tuple[list[str], list[str]]:
    """Compare snapshots and return (critical_failures, allowed_warnings)."""
    critical_failures: list[str] = []
    allowed_warnings: list[str] = []

    # 1. Check ~/.notebooklm-mcp-cli
    for path in sorted(after_mcp_cli.keys() - before_mcp_cli.keys()):
        critical_failures.append(
            f"~/.notebooklm-mcp-cli: added {path} (mtime {after_mcp_cli[path]})"
        )
    for path in sorted(before_mcp_cli.keys() - after_mcp_cli.keys()):
        critical_failures.append(
            f"~/.notebooklm-mcp-cli: removed {path} (was mtime {before_mcp_cli[path]})"
        )
    for path in sorted(before_mcp_cli.keys() & after_mcp_cli.keys()):
        if before_mcp_cli[path] != after_mcp_cli[path]:
            if _is_allowed_live_modification(path):
                allowed_warnings.append(
                    f"~/.notebooklm-mcp-cli: live-modified {path} (mtime {before_mcp_cli[path]} -> {after_mcp_cli[path]})"
                )
            else:
                critical_failures.append(
                    f"~/.notebooklm-mcp-cli: modified {path} (mtime {before_mcp_cli[path]} -> {after_mcp_cli[path]})"
                )

    # 2. Check ~/.notebooklm-mcp (no allowed live-modifications here)
    for path in sorted(after_mcp.keys() - before_mcp.keys()):
        critical_failures.append(f"~/.notebooklm-mcp: added {path} (mtime {after_mcp[path]})")
    for path in sorted(before_mcp.keys() - after_mcp.keys()):
        critical_failures.append(
            f"~/.notebooklm-mcp: removed {path} (was mtime {before_mcp[path]})"
        )
    for path in sorted(before_mcp.keys() & after_mcp.keys()):
        if before_mcp[path] != after_mcp[path]:
            critical_failures.append(
                f"~/.notebooklm-mcp: modified {path} (mtime {before_mcp[path]} -> {after_mcp[path]})"
            )

    return critical_failures, allowed_warnings


def _evaluate_tripwire(
    before_cli: dict[str, StorageFingerprint],
    after_cli: dict[str, StorageFingerprint],
    before_mcp: dict[str, StorageFingerprint],
    after_mcp: dict[str, StorageFingerprint],
) -> tuple[list[str], list[str]]:
    """Evaluate snapshots against tripwire rules, print warnings, and fail on violations."""
    critical_failures, allowed_warnings = _check_tripwire_changes(
        before_cli, after_cli, before_mcp, after_mcp
    )

    if os.environ.get("NLM_OFFLINE_STRICT") == "1":
        critical_failures.extend(allowed_warnings)
        allowed_warnings = []

    if allowed_warnings:
        print("\nStorage tripwire warning (live application files modified during run):")
        for warn in allowed_warnings:
            print(f"  {warn}")

    if critical_failures:
        details = "\n  ".join(critical_failures)
        pytest.fail(
            f"STORAGE TRIPWIRE FAILED: Real developer storage was modified during the test session!\n"
            f"  {details}\n"
            f"Tests must NEVER add, remove, or modify unapproved files in ~/.notebooklm-mcp-cli or ~/.notebooklm-mcp."
        )

    return critical_failures, allowed_warnings


_tripwire_key = pytest.StashKey[
    tuple[Path, Path, dict[str, StorageFingerprint], dict[str, StorageFingerprint]]
]()


def _verify_strict_offline_environment() -> None:
    """Fail before collection unless all inherited filesystem roots are synthetic."""
    if os.environ.get("NLM_OFFLINE_STRICT") != "1":
        return
    # Even the string "0" is truthy to some legacy test selection code.
    # Require these opt-in flags to be absent entirely in strict offline mode.
    if os.environ.get("ALLOW_REAL_KEYSTORE"):
        raise pytest.UsageError("Offline tests cannot access the real OS credential store")
    if os.environ.get("NOTEBOOKLM_E2E"):
        raise pytest.UsageError("Offline tests cannot enable live E2E authentication")
    root_string = os.environ.get("NLM_TEST_ISOLATED_ROOT")
    if not root_string:
        raise pytest.UsageError("NLM_OFFLINE_STRICT requires NLM_TEST_ISOLATED_ROOT")
    root = Path(root_string).resolve()
    monitored = os.environ.get("NLM_OFFLINE_MONITORED_HOME")
    if not monitored or not Path(monitored).is_absolute():
        raise pytest.UsageError("NLM_OFFLINE_STRICT requires absolute NLM_OFFLINE_MONITORED_HOME")
    monitored_home = Path(monitored).resolve()
    if monitored_home.is_relative_to(root) or root.is_relative_to(monitored_home):
        raise pytest.UsageError("Monitored real home and synthetic test root must be disjoint")
    required = (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "NOTEBOOKLM_MCP_CLI_PATH",
    )
    for name in required:
        value = os.environ.get(name)
        if not value or not Path(value).resolve().is_relative_to(root):
            raise pytest.UsageError(f"Unsafe offline test environment: {name}")


def pytest_configure(config):
    """Snapshot real developer storage before collection imports any package module.

    Taken here (not in a session fixture) so writes triggered at import/collection
    time are caught too.
    """
    _verify_strict_offline_environment()
    if os.environ.get("NOTEBOOKLM_E2E") == "1" and os.environ.get("NLM_OFFLINE_STRICT") != "1":
        print("\nStorage tripwire: OFF (NOTEBOOKLM_E2E=1)")
        return

    # Strict mode must monitor the independently pinned real home, not the
    # synthetic HOME/USERPROFILE used by subprocesses. The runner must capture
    # NLM_OFFLINE_MONITORED_HOME *before* redirecting those variables.
    real_home_str = (
        os.environ["NLM_OFFLINE_MONITORED_HOME"]
        if os.environ.get("NLM_OFFLINE_STRICT") == "1"
        else os.environ.get("HOME") or os.environ.get("USERPROFILE")
    )
    if not real_home_str:
        return

    real_home = Path(real_home_str).expanduser()
    real_mcp_cli = real_home / ".notebooklm-mcp-cli"
    real_mcp = real_home / ".notebooklm-mcp"
    config.stash[_tripwire_key] = (
        real_mcp_cli,
        real_mcp,
        _snapshot_storage_dir(real_mcp_cli),
        _snapshot_storage_dir(real_mcp),
    )


def pytest_sessionfinish(session, exitstatus):
    """Fail the test session if any real developer storage is added, removed, or modified."""
    snapshot = session.config.stash.get(_tripwire_key, None)
    if snapshot is None:
        return

    real_mcp_cli, real_mcp, before_cli, before_mcp = snapshot
    try:
        _evaluate_tripwire(
            before_cli,
            _snapshot_storage_dir(real_mcp_cli),
            before_mcp,
            _snapshot_storage_dir(real_mcp),
        )
    except pytest.fail.Exception as exc:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(str(exc), red=True, bold=True)
        else:
            print(f"\n{exc}")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_runtest_setup(item):
    """Prevent explicit live-account paths in the strict offline suite."""
    if os.environ.get("NLM_OFFLINE_STRICT") != "1":
        return
    if item.get_closest_marker("real_os_store") or item.get_closest_marker("wizard_e2e"):
        pytest.fail("Real OS credentials and setup-wizard tests are prohibited offline")
    if item.get_closest_marker("e2e"):
        pytest.fail("Authenticated E2E tests are prohibited offline")


@pytest.fixture(autouse=True)
def _isolate_home(monkeypatch, tmp_path_factory, request):
    """Isolate HOME and Path.home() for every test except real_os_store and explicit e2e."""
    if request.node.get_closest_marker("real_os_store") or (
        os.environ.get("NOTEBOOKLM_E2E") == "1" and request.node.get_closest_marker("e2e")
    ):
        yield
        return

    fake_home = tmp_path_factory.mktemp("fake_home")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    # Subprocesses don't inherit the in-process Path.home monkeypatch.
    # Redirect platform app-data and XDG locations before they can write auth.
    for name, suffix in (
        ("APPDATA", "AppData/Roaming"),
        ("LOCALAPPDATA", "AppData/Local"),
        ("XDG_CONFIG_HOME", ".config"),
        ("XDG_DATA_HOME", ".local/share"),
        ("XDG_CACHE_HOME", ".cache"),
        ("XDG_STATE_HOME", ".local/state"),
        ("TEMP", "Temp"),
        ("TMP", "Temp"),
    ):
        directory = fake_home / suffix
        directory.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(directory))
    if os.name == "nt":
        monkeypatch.setenv("HOMEDRIVE", fake_home.drive)
        monkeypatch.setenv("HOMEPATH", str(fake_home)[len(fake_home.drive) :])
    monkeypatch.setattr(
        Path,
        "home",
        lambda: Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or str(fake_home)),
    )

    yield


@pytest.fixture(autouse=True)
def _isolate_storage(monkeypatch, tmp_path, request):
    """Point all storage (~/.notebooklm-mcp-cli) at a per-test temp dir.

    Several code paths (e.g. BaseClient._update_cached_tokens, headless auth)
    write to the real auth cache and Chrome profile. Without this guard, tests
    that exercise them corrupt the developer's real login.

    Explicitly enabled E2E tests use the real authenticated profile,
    but NLM_AUTH_STORAGE is forced to 'file' to guarantee no migration,
    deletion, or protected-mode code paths can ever run during E2E.
    """
    from notebooklm_tools.utils.config import reset_config

    if os.environ.get("NOTEBOOKLM_E2E") == "1" and request.node.get_closest_marker("e2e"):
        monkeypatch.setenv("NLM_AUTH_STORAGE", "file")
        reset_config()
        try:
            yield
        finally:
            reset_config()
        return

    from notebooklm_tools.mcp.tools._utils import reset_mcp_probe_state

    reset_mcp_probe_state()
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))
    reset_config()
    try:
        yield
    finally:
        reset_config()
        reset_mcp_probe_state()


@pytest.fixture(autouse=True)
def _disable_cookie_rotation(monkeypatch):
    """Keep tests from hitting accounts.google.com.

    BaseClient._call_rpc rotates Google cookies before real RPC calls; a test
    with a mocked HTTP client could otherwise "succeed" at rotation against
    the mock. Tests that exercise rotation itself re-enable it with
    monkeypatch.delenv.
    """
    from notebooklm_tools.core.cookie_rotation import DISABLE_ROTATE_COOKIES_ENV

    monkeypatch.setenv(DISABLE_ROTATE_COOKIES_ENV, "1")


@pytest.fixture(autouse=True)
def _guard_credential_store(request, monkeypatch):
    """Enforce fail-closed credential store access during tests.

    Normal tests must NEVER open the real OS keystore (macOS Keychain,
    Windows Credential Manager, SecretService). Only explicit platform smoke
    tests marked with @pytest.mark.real_os_store may do so with guaranteed cleanup.
    """
    if request.node.get_closest_marker("real_os_store"):
        yield
        return

    import keyring

    import notebooklm_tools.core.credential_store as cs
    from notebooklm_tools.core.credential_store import (
        FailClosedCredentialBackend,
        FailClosedKeyring,
        RealCredentialStoreAccessAttemptedError,
        get_backend_factory,
        set_backend_factory,
    )

    def _fail_detect():
        raise RealCredentialStoreAccessAttemptedError(
            "Direct OS backend detection attempted in test (_detect_os_backend)"
        )

    old_keyring = keyring.get_keyring()
    old_factory = get_backend_factory()

    keyring.set_keyring(FailClosedKeyring())
    set_backend_factory(lambda: FailClosedCredentialBackend())
    monkeypatch.setattr(cs, "_detect_os_backend", _fail_detect)

    try:
        yield
    finally:
        keyring.set_keyring(old_keyring)
        set_backend_factory(old_factory)


@pytest.fixture
def pretend_desktop(monkeypatch):
    """Make the 'is this an SSH/container/headless session?' hint say no.

    CI runs on headless Linux, where Protected mode invites are (correctly)
    suppressed. Tests that check an invite appears need a desktop session.
    """
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(
        "notebooklm_tools.core.credential_backend_worker.is_definitely_non_desktop",
        lambda: False,
    )


@pytest.fixture
def fake_credential_store():
    """Provide an in-memory fake credential store for tests that test protected mode."""
    from notebooklm_tools.core.credential_store import (
        InMemoryCredentialBackend,
        get_backend_factory,
        set_backend_factory,
    )

    backend = InMemoryCredentialBackend()
    old_factory = get_backend_factory()
    set_backend_factory(lambda: backend)
    try:
        yield backend
    finally:
        set_backend_factory(old_factory)
