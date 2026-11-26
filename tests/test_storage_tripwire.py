"""Tests verifying the suite-level storage tripwire behavior using temporary directories."""

import os
from pathlib import Path

import pytest
from conftest import (
    _check_tripwire_changes,
    _evaluate_tripwire,
    _is_allowed_live_modification,
    _snapshot_storage_dir,
)


def test_is_allowed_live_modification():
    """Verify the allowlist of live-written application files."""
    assert _is_allowed_live_modification("auth.json") is True
    assert _is_allowed_live_modification("update_check.json") is True
    assert _is_allowed_live_modification("cache/update_check.json") is True
    assert _is_allowed_live_modification("profiles/default/cookies.json") is True
    assert _is_allowed_live_modification("profiles/work/metadata.json") is True

    # Unapproved modifications must NOT be allowed
    assert _is_allowed_live_modification("notices.json") is False
    assert _is_allowed_live_modification("installation.json") is False
    assert _is_allowed_live_modification("config.toml") is False
    assert _is_allowed_live_modification("profiles/default/credentials.enc") is False


def test_tripwire_fails_on_added_file(tmp_path: Path):
    """Tripwire detects when a file is newly created in storage."""
    fake_cli = tmp_path / ".notebooklm-mcp-cli"
    fake_mcp = tmp_path / ".notebooklm-mcp"
    fake_cli.mkdir(parents=True, exist_ok=True)
    fake_mcp.mkdir(parents=True, exist_ok=True)

    before_cli = _snapshot_storage_dir(fake_cli)
    before_mcp = _snapshot_storage_dir(fake_mcp)

    # Simulate a rogue test writing a new file
    (fake_cli / "rogue_file.json").write_text("{}", encoding="utf-8")

    after_cli = _snapshot_storage_dir(fake_cli)
    after_mcp = _snapshot_storage_dir(fake_mcp)

    critical, warnings = _check_tripwire_changes(before_cli, after_cli, before_mcp, after_mcp)
    assert len(critical) == 1
    assert "added rogue_file.json" in critical[0]

    # Deliberately prove that the tripwire fails when evaluated
    with pytest.raises(pytest.fail.Exception, match="STORAGE TRIPWIRE FAILED"):
        _evaluate_tripwire(before_cli, after_cli, before_mcp, after_mcp)


def test_tripwire_fails_on_removed_file(tmp_path: Path):
    """Tripwire detects when an existing file is deleted from storage."""
    fake_cli = tmp_path / ".notebooklm-mcp-cli"
    fake_mcp = tmp_path / ".notebooklm-mcp"
    fake_cli.mkdir(parents=True, exist_ok=True)
    fake_mcp.mkdir(parents=True, exist_ok=True)

    existing_file = fake_cli / "auth.json"
    existing_file.write_text("{}", encoding="utf-8")

    before_cli = _snapshot_storage_dir(fake_cli)
    before_mcp = _snapshot_storage_dir(fake_mcp)

    # Simulate file removal
    existing_file.unlink()

    after_cli = _snapshot_storage_dir(fake_cli)
    after_mcp = _snapshot_storage_dir(fake_mcp)

    critical, warnings = _check_tripwire_changes(before_cli, after_cli, before_mcp, after_mcp)
    assert len(critical) == 1
    assert "removed auth.json" in critical[0]

    with pytest.raises(pytest.fail.Exception, match="STORAGE TRIPWIRE FAILED"):
        _evaluate_tripwire(before_cli, after_cli, before_mcp, after_mcp)


def test_tripwire_tolerates_live_modifications(tmp_path: Path):
    """Tripwire tolerates modification of live application files (cookies, metadata, root auth)."""
    fake_cli = tmp_path / ".notebooklm-mcp-cli"
    fake_mcp = tmp_path / ".notebooklm-mcp"
    fake_cli.mkdir(parents=True, exist_ok=True)
    fake_mcp.mkdir(parents=True, exist_ok=True)

    profile_dir = fake_cli / "profiles" / "work"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cookies_file = profile_dir / "cookies.json"
    cookies_file.write_text("{}", encoding="utf-8")

    before_cli = _snapshot_storage_dir(fake_cli)
    before_mcp = _snapshot_storage_dir(fake_mcp)

    # Simulate cookie rotation updating mtime
    cookies_file.write_text('{"rotated": true}', encoding="utf-8")

    after_cli = _snapshot_storage_dir(fake_cli)
    after_mcp = _snapshot_storage_dir(fake_mcp)

    critical, warnings = _check_tripwire_changes(before_cli, after_cli, before_mcp, after_mcp)
    # Critical failures MUST be empty for allowlisted files
    assert len(critical) == 0
    # Must be reported in warnings
    assert len(warnings) == 1
    assert "live-modified profiles/work/cookies.json" in warnings[0]

    if os.environ.get("NLM_OFFLINE_STRICT") == "1":
        # Strict offline runs must reject even normally allowlisted writes.
        with pytest.raises(pytest.fail.Exception, match="STORAGE TRIPWIRE FAILED"):
            _evaluate_tripwire(before_cli, after_cli, before_mcp, after_mcp)
    else:
        _evaluate_tripwire(before_cli, after_cli, before_mcp, after_mcp)


def test_tripwire_fails_on_unapproved_modification(tmp_path: Path):
    """Tripwire fails when a non-allowlisted file (e.g. notices.json) is modified."""
    fake_cli = tmp_path / ".notebooklm-mcp-cli"
    fake_mcp = tmp_path / ".notebooklm-mcp"
    fake_cli.mkdir(parents=True, exist_ok=True)
    fake_mcp.mkdir(parents=True, exist_ok=True)

    notices_file = fake_cli / "notices.json"
    notices_file.write_text("{}", encoding="utf-8")

    before_cli = _snapshot_storage_dir(fake_cli)
    before_mcp = _snapshot_storage_dir(fake_mcp)

    notices_file.write_text('{"modified": true}', encoding="utf-8")

    after_cli = _snapshot_storage_dir(fake_cli)
    after_mcp = _snapshot_storage_dir(fake_mcp)

    critical, warnings = _check_tripwire_changes(before_cli, after_cli, before_mcp, after_mcp)
    assert len(critical) == 1
    assert "modified notices.json" in critical[0]

    with pytest.raises(pytest.fail.Exception, match="STORAGE TRIPWIRE FAILED"):
        _evaluate_tripwire(before_cli, after_cli, before_mcp, after_mcp)


def test_tripwire_fails_on_added_file_legacy(tmp_path: Path):
    """Tripwire detects when a file is newly created in legacy ~/.notebooklm-mcp."""
    fake_cli = tmp_path / ".notebooklm-mcp-cli"
    fake_mcp = tmp_path / ".notebooklm-mcp"
    fake_cli.mkdir(parents=True, exist_ok=True)
    fake_mcp.mkdir(parents=True, exist_ok=True)

    before_cli = _snapshot_storage_dir(fake_cli)
    before_mcp = _snapshot_storage_dir(fake_mcp)

    (fake_mcp / "rogue_legacy.json").write_text("{}", encoding="utf-8")

    after_cli = _snapshot_storage_dir(fake_cli)
    after_mcp = _snapshot_storage_dir(fake_mcp)

    critical, warnings = _check_tripwire_changes(before_cli, after_cli, before_mcp, after_mcp)
    assert len(critical) == 1
    assert "~/.notebooklm-mcp: added rogue_legacy.json" in critical[0]

    with pytest.raises(pytest.fail.Exception, match="STORAGE TRIPWIRE FAILED"):
        _evaluate_tripwire(before_cli, after_cli, before_mcp, after_mcp)
