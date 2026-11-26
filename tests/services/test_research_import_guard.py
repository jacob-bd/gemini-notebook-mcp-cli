"""Synthetic tests for durable, fail-closed research import claims."""

import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from time import sleep

import pytest

from notebooklm_tools.services import _research_import_guard as guard


class _Client:
    def __init__(self, profile="qa"):
        self._profile_name = profile
        self._is_env_auth = False


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "private-storage"))


def test_repeated_confirmation_is_not_replayed():
    sends = []

    def send():
        sends.append("send")

    first = guard.import_once(_Client(), "nb", "task", send)
    second = guard.import_once(_Client(), "nb", "task", send)
    assert first == second == (True, "confirmed", None)
    assert sends == ["send"]


def test_failed_provider_operation_stays_unconfirmed_across_clients():
    sends = []

    def unknown():
        sends.append("sent")
        raise TimeoutError("provider may have accepted request")

    first = guard.import_once(_Client(), "nb", "task", unknown)
    second = guard.import_once(_Client(), "nb", "task", unknown)
    assert first == second == (None, "unconfirmed", "import_unconfirmed")
    assert sends == ["sent"]


def test_profile_notebook_and_task_are_independent():
    sends = []
    for client, notebook, task in (
        (_Client("one"), "nb", "task"),
        (_Client("two"), "nb", "task"),
        (_Client("one"), "nb2", "task"),
        (_Client("one"), "nb", "task2"),
    ):
        result = guard.import_once(client, notebook, task, lambda: sends.append(1))
        assert result == (True, "confirmed", None)
    assert len(sends) == 4


def _process_attempt(args):
    """Separate spawned interpreters must observe the same durable claim."""
    storage, marker = args
    os.environ["NOTEBOOKLM_MCP_CLI_PATH"] = storage

    def send():
        with Path(marker).open("a", encoding="utf-8") as handle:
            handle.write("sent\n")
        sleep(0.1)

    return guard.import_once(_Client(), "nb", "cross-process-task", send)


def test_concurrent_processes_share_one_mutation(tmp_path):
    root = tmp_path / "shared-private-storage"
    marker = tmp_path / "provider-attempts.txt"
    arguments = (str(root), str(marker))
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(_process_attempt, [arguments, arguments]))
    assert marker.read_text(encoding="utf-8").splitlines() == ["sent"]
    assert all(state in {"confirmed", "unconfirmed"} for _, state, _ in results)


def test_concurrent_calls_share_one_mutation():
    count = 0
    lock = Lock()

    def send():
        nonlocal count
        with lock:
            count += 1
        sleep(0.03)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: guard.import_once(_Client(), "nb", "task", send), range(8))
        )
    assert count == 1
    assert any(result[1] == "confirmed" for result in results)
    assert all(result[1] in {"confirmed", "unconfirmed"} for result in results)


def test_corrupt_or_pending_claim_fails_closed():
    client = _Client()
    path = guard._claim_path(client, "nb", "task")
    path.write_text("{corrupt", encoding="utf-8")
    sends = []
    result = guard.import_once(client, "nb", "task", lambda: sends.append(1))
    assert result == (None, "unconfirmed", "import_unconfirmed")
    assert not sends


def test_confirmation_write_failure_does_not_replay(monkeypatch):
    sends = []

    def failed_publish(path):
        raise OSError("disk full")

    monkeypatch.setattr(guard, "_mark_confirmed", failed_publish)
    client = _Client()
    first = guard.import_once(client, "nb", "task", lambda: sends.append(1))
    second = guard.import_once(client, "nb", "task", lambda: sends.append(1))
    assert first == second == (None, "unconfirmed", "import_unconfirmed")
    assert sends == [1]


def test_unidentified_environment_auth_cannot_auto_import():
    client = _Client()
    client._profile_name = None
    client._is_env_auth = True
    calls = []
    assert guard.import_once(client, "nb", "task", lambda: calls.append(1)) == (
        None,
        "guard_unavailable",
        "import_guard_unavailable",
    )
    assert not calls


def test_unbound_non_environment_profile_fails_closed():
    client = _Client()
    client._profile_name = None
    client._is_env_auth = False
    sends = []
    result = guard.import_once(client, "nb", "task", lambda: sends.append(1))
    assert result == (None, "guard_unavailable", "import_guard_unavailable")
    assert not sends


def test_symlinked_confirmation_cannot_forge_success():
    client = _Client()
    path = guard._claim_path(client, "nb", "task")
    forged = path.parent / "forged.json"
    forged.write_text('{"state":"confirmed"}', encoding="utf-8")
    try:
        path.symlink_to(forged)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not available for this test account")
    sent = []
    result = guard.import_once(client, "nb", "task", lambda: sent.append(1))
    assert result == (None, "unconfirmed", "import_unconfirmed")
    assert sent == []


def test_junction_or_symlink_in_storage_parent_blocks_sends(tmp_path, monkeypatch):
    target = tmp_path / "real-storage"
    target.mkdir()
    linked = tmp_path / "linked-storage"
    try:
        linked.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory links not available for this account")
    monkeypatch.setattr(guard, "get_storage_dir", lambda: linked)
    sends = []
    result = guard.import_once(_Client(), "nb", "task", lambda: sends.append(1))
    assert result == (None, "guard_unavailable", "import_guard_unavailable")
    assert sends == []


def test_unwritable_claim_location_fails_before_provider_call(monkeypatch):
    def invalid_path(*args):
        raise OSError("storage denied")

    monkeypatch.setattr(guard, "_claim_path", invalid_path)
    sends = []
    result = guard.import_once(_Client(), "nb", "task", lambda: sends.append(1))
    assert result == (None, "guard_unavailable", "import_guard_unavailable")
    assert not sends
