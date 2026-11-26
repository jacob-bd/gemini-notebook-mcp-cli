"""Regression checks for synthetic offline auth and subprocess directory isolation."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import _evaluate_tripwire, _verify_strict_offline_environment


def test_subprocess_inherits_only_synthetic_appdata(tmp_path):
    root = Path(os.environ["NLM_TEST_ISOLATED_ROOT"]).resolve()
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

    # Authentication material here is synthetic, never copied from a real profile.
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


def test_offline_guard_rejects_unisolated_windows_appdata(monkeypatch):
    root = Path(os.environ["NLM_TEST_ISOLATED_ROOT"]).resolve()
    monkeypatch.setenv("APPDATA", str(root.parent / "outside-offline-root"))
    with pytest.raises(pytest.UsageError, match="APPDATA"):
        _verify_strict_offline_environment()


def test_strict_offline_suite_blocks_real_keystore_marker():
    from conftest import pytest_runtest_setup

    class RealStoreItem:
        def get_closest_marker(self, name):
            return object() if name == "real_os_store" else None

    with pytest.raises(pytest.fail.Exception, match="prohibited offline"):
        pytest_runtest_setup(RealStoreItem())
