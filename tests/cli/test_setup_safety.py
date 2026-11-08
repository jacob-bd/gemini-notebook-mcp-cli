"""Tests for safe configuration file handling and backups."""

import json
import os
import stat
from pathlib import Path

import pytest

from notebooklm_tools.cli.setup_safety import (
    ConfigParseError,
    atomic_write_text,
    backup_existing,
    capture_backups,
    read_json_config,
)


def _assert_posix_mode(path: Path, expected: int) -> None:
    """Assert exact mode only where chmod has POSIX permission semantics."""
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == expected


def test_missing_json_returns_empty_dict(tmp_path):
    path = tmp_path / "missing.json"
    assert read_json_config(path) == {}


@pytest.mark.parametrize("content", ["", "   \n\t  "], ids=["empty", "whitespace"])
def test_blank_json_returns_empty_dict(tmp_path, content):
    path = tmp_path / "blank.json"
    path.write_text(content, encoding="utf-8")

    assert read_json_config(path) == {}
    assert path.read_text(encoding="utf-8") == content


def test_json_read_error_is_wrapped(tmp_path, monkeypatch):
    path = tmp_path / "mcp.json"
    path.write_text("{}", encoding="utf-8")
    cause = OSError("cannot read config")

    def fail_read(*args, **kwargs):
        raise cause

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(ConfigParseError) as exc_info:
        read_json_config(path)
    assert exc_info.value.path == path
    assert exc_info.value.cause is cause
    assert exc_info.value.__cause__ is cause


def test_valid_json_returns_dict(tmp_path):
    path = tmp_path / "valid.json"
    path.write_text('{"mcpServers": {"test": {}}}', encoding="utf-8")
    assert read_json_config(path) == {"mcpServers": {"test": {}}}


def test_malformed_json_is_not_replaced(tmp_path):
    path = tmp_path / "mcp.json"
    original = '{"servers": {,}'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ConfigParseError) as exc_info:
        read_json_config(path)
    assert exc_info.value.path == path
    assert path.read_text(encoding="utf-8") == original


def test_json_non_dict_raises_config_parse_error(tmp_path):
    path = tmp_path / "array.json"
    path.write_text('["not", "an", "object"]', encoding="utf-8")
    with pytest.raises(ConfigParseError) as exc_info:
        read_json_config(path)
    assert exc_info.value.path == path


def test_atomic_write_rejects_symlink(tmp_path):
    target = tmp_path / "real.json"
    target.write_text('{"keep": true}', encoding="utf-8")
    link = tmp_path / "mcp.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic link"):
        atomic_write_text(link, '{"keep": false}')
    assert target.read_text(encoding="utf-8") == '{"keep": true}'


def test_atomic_write_preserves_permissions(tmp_path):
    target = tmp_path / "mode.json"
    target.write_text('{"val": 1}', encoding="utf-8")
    target.chmod(0o640)
    atomic_write_text(target, '{"val": 2}')
    assert target.read_text(encoding="utf-8") == '{"val": 2}'
    _assert_posix_mode(target, 0o640)


def test_backup_existing_file(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(fake_home / ".notebooklm-mcp-cli"))

    config_file = tmp_path / "app_config.json"
    config_file.write_text('{"key": "original"}', encoding="utf-8")

    backup_path = backup_existing(config_file, label="test-config")
    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.is_file()
    assert backup_path.parent == fake_home / ".notebooklm-mcp-cli" / "backups"
    _assert_posix_mode(backup_path, 0o600)
    _assert_posix_mode(backup_path.parent, 0o700)
    assert json.loads(backup_path.read_text(encoding="utf-8")) == {"key": "original"}


def test_backup_existing_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(fake_home / ".notebooklm-mcp-cli"))

    skill_dir = tmp_path / "nlm-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n", encoding="utf-8")
    ref_dir = skill_dir / "references"
    ref_dir.mkdir()
    (ref_dir / "guide.md").write_text("# Guide", encoding="utf-8")

    backup_path = backup_existing(skill_dir, label="test-skill")
    assert backup_path is not None
    assert backup_path.exists()
    assert backup_path.is_dir()
    assert (backup_path / "SKILL.md").read_text(encoding="utf-8") == "---\nname: test\n---\n"
    assert (backup_path / "references" / "guide.md").read_text(encoding="utf-8") == "# Guide"
    _assert_posix_mode(backup_path, 0o700)


def test_backup_existing_rejects_symlink(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(fake_home / ".notebooklm-mcp-cli"))

    real_file = tmp_path / "real.json"
    real_file.write_text("{}")
    link_file = tmp_path / "link.json"
    link_file.symlink_to(real_file)

    with pytest.raises(ValueError, match="symbolic link"):
        backup_existing(link_file, label="link-test")


def test_backup_existing_rejects_symlink_backup_root(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(fake_home / ".notebooklm-mcp-cli"))

    real_backups = tmp_path / "other_backups"
    real_backups.mkdir()
    link_root = fake_home / ".notebooklm-mcp-cli" / "backups"
    link_root.parent.mkdir(parents=True)
    link_root.symlink_to(real_backups)

    config_file = tmp_path / "conf.json"
    config_file.write_text("{}")

    with pytest.raises(ValueError, match="symbolic-link backup root"):
        backup_existing(config_file, label="test")


def test_capture_backups_records_paths(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(fake_home / ".notebooklm-mcp-cli"))

    file_a = tmp_path / "a.json"
    file_a.write_text('{"a": 1}')
    file_b = tmp_path / "b.json"
    file_b.write_text('{"b": 2}')

    with capture_backups() as recorded:
        backup_existing(file_a, label="first")
        backup_existing(file_b, label="second")

    assert len(recorded) == 2
    assert recorded[0].name.endswith("-first")
    assert recorded[1].name.endswith("-second")
