"""The WSL firewall probe must return its documented bool result."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from notebooklm_tools.utils import wsl


@pytest.mark.parametrize(
    ("returncode", "output", "expected"),
    [
        (0, "NotebookLM-CDP-9222\n", True),
        (0, "   \n", False),
        (1, "NotebookLM-CDP-9222\n", False),
    ],
)
def test_firewall_rule_check_is_boolean(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    output: str,
    expected: bool,
) -> None:
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl, "_get_powershell_path", lambda: Path("pwsh.exe"))
    run = Mock(
        return_value=subprocess.CompletedProcess(
            ["pwsh.exe"], returncode=returncode, stdout=output, stderr=""
        )
    )
    monkeypatch.setattr(wsl.subprocess, "run", run)

    found = wsl.check_firewall_rule(9222)

    assert type(found) is bool
    assert found is expected
    run.assert_called_once()


def test_firewall_rule_check_without_powershell_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    monkeypatch.setattr(wsl, "_get_powershell_path", lambda: None)

    assert wsl.check_firewall_rule(9222) is False
