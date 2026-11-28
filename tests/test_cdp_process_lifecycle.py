"""Tests for Chrome subprocess pipe handling, startup diagnostics, and reaping."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

from notebooklm_tools.utils import cdp


def test_launch_chrome_process_does_not_deadlock_on_large_output(tmp_path):
    """Chrome writing >64 KiB to stdout/stderr must not deadlock on unread pipes."""
    real_popen = subprocess.Popen
    child_code = (
        "import sys; "
        "sys.stdout.write('o' * 131072); sys.stdout.flush(); "
        "sys.stderr.write('e' * 131072); "
        "sys.stderr.write('\\nfinal startup error\\n'); sys.stderr.flush(); "
        "sys.exit(1)"
    )

    def fake_popen(_args, **kwargs):
        return real_popen(
            [sys.executable, "-c", child_code],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
        )

    with (
        patch.object(cdp, "get_chrome_path", return_value="/fake/chrome"),
        patch.object(cdp, "_get_profile_dir_for_launch", return_value=tmp_path),
        patch.object(cdp.subprocess, "Popen", side_effect=fake_popen),
    ):
        proc = cdp.launch_chrome_process(port=9222, headless=True, profile_name="default")

    assert proc is not None
    try:
        assert proc.wait(timeout=3) == 1
        summary = cdp._summarize_browser_startup_failure(proc)
        assert summary == "Exit code 1: final startup error"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        for stream in (proc.stdout, proc.stderr, getattr(proc, "_nlm_stderr_file", None)):
            if stream is not None:
                stream.close()


def test_summarize_startup_failure_does_not_block_on_inherited_grandchild_stderr(tmp_path):
    """Startup-failure summary must return immediately even if a grandchild holds stderr open."""
    real_popen = subprocess.Popen
    child_code = (
        "import subprocess, sys; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2.5)'], "
        "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=sys.stderr, close_fds=False); "
        "sys.stderr.write('handed off to existing Chrome\\n'); sys.stderr.flush(); "
        "sys.exit(1)"
    )

    def fake_popen(_args, **kwargs):
        return real_popen(
            [sys.executable, "-c", child_code],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
        )

    with (
        patch.object(cdp, "get_chrome_path", return_value="/fake/chrome"),
        patch.object(cdp, "_get_profile_dir_for_launch", return_value=tmp_path),
        patch.object(cdp.subprocess, "Popen", side_effect=fake_popen),
    ):
        proc = cdp.launch_chrome_process(port=9222, headless=False, profile_name="default")

    assert proc is not None
    try:
        assert proc.wait(timeout=3) == 1
        t0 = time.monotonic()
        summary = cdp._summarize_browser_startup_failure(proc)
        elapsed = time.monotonic() - t0
        assert summary == "Exit code 1: handed off to existing Chrome"
        assert elapsed < 1.0, f"_summarize_browser_startup_failure blocked for {elapsed:.2f}s"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        for stream in (proc.stdout, proc.stderr, getattr(proc, "_nlm_stderr_file", None)):
            if stream is not None:
                stream.close()


def test_terminate_chrome_reaps_after_kill_and_closes_stderr_capture():
    """terminate_chrome must reap after kill() and close attached stdio/stderr handles."""
    proc = MagicMock()
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="chrome", timeout=5),
        subprocess.TimeoutExpired(cmd="chrome", timeout=5),
        0,
    ]
    with tempfile.TemporaryFile() as stderr_file:
        proc._nlm_stderr_file = stderr_file
        proc.stdout = None
        proc.stderr = None

        with patch.object(cdp, "_clear_port_map"):
            assert cdp.terminate_chrome(proc, port=None) is True

        proc.kill.assert_called_once()
        assert proc.wait.call_count == 3
        assert stderr_file.closed


def test_launch_chrome_process_closes_stderr_file_on_popen_error(tmp_path):
    """If subprocess.Popen fails, any temporary stderr file created for Chrome is closed."""
    created: list = []
    real_tmp = tempfile.TemporaryFile

    def track_tmp(*args, **kwargs):
        fh = real_tmp(*args, **kwargs)
        created.append(fh)
        return fh

    with (
        patch.object(cdp, "get_chrome_path", return_value="/fake/chrome"),
        patch.object(cdp, "_get_profile_dir_for_launch", return_value=tmp_path),
        patch.object(cdp.tempfile, "TemporaryFile", side_effect=track_tmp),
        patch.object(cdp.subprocess, "Popen", side_effect=OSError("exec failed")),
    ):
        assert cdp.launch_chrome_process(port=9222, headless=True, profile_name="default") is None

    assert len(created) == 1
    assert created[0].closed
