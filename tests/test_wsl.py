"""Tests for WSL networking utilities."""

import subprocess
from unittest.mock import Mock, call

from notebooklm_tools.utils import wsl


def _result(args: list[str], stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode=0, stdout=stdout, stderr="")


def test_get_windows_host_ip_uses_loopback_in_mirrored_mode(monkeypatch):
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    run = Mock(return_value=_result(["wslinfo", "--networking-mode"], "mirrored\n"))
    monkeypatch.setattr(wsl.subprocess, "run", run)

    assert wsl.get_windows_host_ip() == "127.0.0.1"
    run.assert_called_once_with(
        ["wslinfo", "--networking-mode"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )


def test_get_windows_host_ip_uses_gateway_in_nat_mode(monkeypatch):
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)
    run = Mock(
        side_effect=[
            _result(["wslinfo", "--networking-mode"], "nat\n"),
            _result(["ip", "route"], "default via 172.20.112.1 dev eth0\n"),
        ]
    )
    monkeypatch.setattr(wsl.subprocess, "run", run)

    assert wsl.get_windows_host_ip() == "172.20.112.1"
    assert run.call_args_list == [
        call(
            ["wslinfo", "--networking-mode"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ),
        call(["ip", "route"], capture_output=True, text=True, check=True),
    ]


def test_get_windows_host_ip_uses_gateway_when_wslinfo_is_unavailable(monkeypatch):
    monkeypatch.setattr(wsl, "is_wsl", lambda: True)

    def run(args, **kwargs):
        if args[0] == "wslinfo":
            raise FileNotFoundError
        return _result(args, "default via 172.20.112.1 dev eth0\n")

    monkeypatch.setattr(wsl.subprocess, "run", run)

    assert wsl.get_windows_host_ip() == "172.20.112.1"
