"""Regression checks for synthetic offline auth and subprocess directory isolation."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import (
    _evaluate_tripwire,
    _tripwire_key,
    _verify_strict_offline_environment,
    pytest_configure,
)


def _set_strict_environment(monkeypatch, root: Path, monitored: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    monitored.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("NLM_OFFLINE_STRICT", "1")
    monkeypatch.setenv("NLM_TEST_ISOLATED_ROOT", str(root))
    monkeypatch.setenv("NLM_OFFLINE_MONITORED_HOME", str(monitored))
    monkeypatch.delenv("ALLOW_REAL_KEYSTORE", raising=False)
    monkeypatch.delenv("NOTEBOOKLM_E2E", raising=False)
    for name, suffix in (
        ("HOME", "home"),
        ("USERPROFILE", "home"),
        ("APPDATA", "AppData/Roaming"),
        ("LOCALAPPDATA", "AppData/Local"),
        ("XDG_CONFIG_HOME", ".config"),
        ("XDG_DATA_HOME", ".local/share"),
        ("XDG_CACHE_HOME", ".cache"),
        ("XDG_STATE_HOME", ".local/state"),
        ("TEMP", "tmp"),
        ("TMP", "tmp"),
        ("NOTEBOOKLM_MCP_CLI_PATH", "storage"),
    ):
        directory = root / suffix
        directory.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv(name, str(directory))


def test_subprocess_inherits_only_synthetic_appdata(tmp_path, monkeypatch):
    root = tmp_path / "synthetic"
    monitored = tmp_path / "watched-real-home"
    _set_strict_environment(monkeypatch, root, monitored)
    _verify_strict_offline_environment()
    names = (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "TEMP",
        "TMP",
        "NOTEBOOKLM_MCP_CLI_PATH",
    )
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json, os; print(json.dumps({k:os.environ[k] for k in " + repr(names) + "}))",
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    for path in json.loads(child.stdout).values():
        assert Path(path).resolve().is_relative_to(root)
    synthetic_auth = Path(os.environ["NOTEBOOKLM_MCP_CLI_PATH"]) / "profiles" / "fixture"
    synthetic_auth.mkdir(parents=True)
    (synthetic_auth / "cookies.json").write_text('{"synthetic": true}', encoding="utf-8")
    assert (synthetic_auth / "cookies.json").is_relative_to(root)


def test_strict_tripwire_rejects_even_allowlisted_auth_changes(monkeypatch):
    monkeypatch.setenv("NLM_OFFLINE_STRICT", "1")
    with pytest.raises(pytest.fail.Exception, match="STORAGE TRIPWIRE FAILED"):
        _evaluate_tripwire(
            {"auth.json": (1, 12)},
            {"auth.json": (2, 12)},
            {},
            {},
        )


def test_offline_guard_rejects_unisolated_windows_appdata(monkeypatch, tmp_path):
    _set_strict_environment(monkeypatch, tmp_path / "synthetic", tmp_path / "monitored")
    monkeypatch.setenv("APPDATA", str(tmp_path / "outside-offline-root"))
    with pytest.raises(pytest.UsageError, match="APPDATA"):
        _verify_strict_offline_environment()


def test_monitor_home_required_and_disjoint(monkeypatch, tmp_path):
    root = tmp_path / "synthetic"
    watched = tmp_path / "watched"
    _set_strict_environment(monkeypatch, root, watched)
    monkeypatch.delenv("NLM_OFFLINE_MONITORED_HOME")
    with pytest.raises(pytest.UsageError, match="NLM_OFFLINE_MONITORED_HOME"):
        _verify_strict_offline_environment()
    monkeypatch.setenv("NLM_OFFLINE_MONITORED_HOME", str(root / "wrong"))
    with pytest.raises(pytest.UsageError, match="disjoint"):
        _verify_strict_offline_environment()


def test_strict_configure_monitors_pinned_home_not_synthetic_home(monkeypatch, tmp_path):
    root = tmp_path / "synthetic"
    watched = tmp_path / "independent-home"
    _set_strict_environment(monkeypatch, root, watched)
    config = SimpleNamespace(stash={})
    pytest_configure(config)
    real_cli, real_mcp, _before_cli, _before_mcp = config.stash[_tripwire_key]
    assert real_cli == watched / ".notebooklm-mcp-cli"
    assert real_mcp == watched / ".notebooklm-mcp"
    assert not real_cli.is_relative_to(root)


def test_strict_offline_suite_blocks_live_markers(monkeypatch):
    from conftest import pytest_runtest_setup

    monkeypatch.setenv("NLM_OFFLINE_STRICT", "1")

    class LiveItem:
        def __init__(self, marker):
            self.marker = marker

        def get_closest_marker(self, name):
            return object() if name == self.marker else None

    for marker in ("real_os_store", "wizard_e2e", "e2e"):
        with pytest.raises(pytest.fail.Exception, match="prohibited offline"):
            pytest_runtest_setup(LiveItem(marker))


@pytest.mark.parametrize("flag_value", ["0", "1"])
def test_strict_offline_suite_rejects_e2e_flag(monkeypatch, tmp_path, flag_value):
    _set_strict_environment(monkeypatch, tmp_path / "synthetic", tmp_path / "monitored")
    monkeypatch.setenv("NOTEBOOKLM_E2E", flag_value)
    with pytest.raises(pytest.UsageError, match="E2E"):
        _verify_strict_offline_environment()


@pytest.mark.parametrize("flag_value", ["0", "1"])
def test_strict_offline_suite_rejects_keystore_optin(monkeypatch, tmp_path, flag_value):
    _set_strict_environment(monkeypatch, tmp_path / "synthetic", tmp_path / "monitored")
    monkeypatch.setenv("ALLOW_REAL_KEYSTORE", flag_value)
    with pytest.raises(pytest.UsageError, match="credential store"):
        _verify_strict_offline_environment()
