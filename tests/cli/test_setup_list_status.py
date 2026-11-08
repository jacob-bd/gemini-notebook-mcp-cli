"""The direct status command reports the same user-level targets as the wizard."""

import json
from pathlib import Path

import pytest
from rich.console import Console

from notebooklm_tools.cli.commands import setup


def test_setup_list_shows_desktop_only_codex_config(tmp_path, monkeypatch, capsys):
    console = Console(record=True, width=180)
    monkeypatch.setattr(setup, "console", console)
    config_dir = tmp_path / ".codex"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        '[mcp_servers.gemini-notebook-mcp]\ncommand = "/bin/notebooklm-mcp"\n'
    )
    monkeypatch.setattr(setup, "_codex_config_path", lambda: config_dir)
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        setup,
        "CLIENT_REGISTRY",
        {"codex": {"name": "Codex", "description": "Codex", "has_auto_setup": True}},
    )

    setup.setup_list()

    output = console.export_text()
    assert "✓" in output
    assert "config.toml" in output


def test_setup_list_does_not_claim_unrelated_claude_legacy_entry(tmp_path, monkeypatch, capsys):
    console = Console(record=True, width=180)
    monkeypatch.setattr(setup, "console", console)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"notebooklm": {"command": "unrelated-tool"}}})
    )
    monkeypatch.setattr(
        setup.shutil, "which", lambda name: "/bin/claude" if name == "claude" else None
    )
    monkeypatch.setattr(
        setup.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": "notebooklm: unrelated-tool"})(),
    )
    monkeypatch.setattr(
        setup,
        "CLIENT_REGISTRY",
        {
            "claude-code": {
                "name": "Claude Code",
                "description": "Claude Code",
                "has_auto_setup": True,
            }
        },
    )

    setup.setup_list()

    assert "✓" not in console.export_text()


def test_setup_list_shows_global_copilot_config(tmp_path, monkeypatch, capsys):
    console = Console(record=True, width=180)
    monkeypatch.setattr(setup, "console", console)
    user_config = tmp_path / "User" / "mcp.json"
    user_config.parent.mkdir()
    user_config.write_text(
        json.dumps({"servers": {"gemini-notebook-mcp": {"command": "/bin/notebooklm-mcp"}}})
    )
    monkeypatch.setattr(
        setup,
        "_github_copilot_config_path",
        lambda scope="project": (
            user_config if scope == "user" else tmp_path / ".vscode" / "mcp.json"
        ),
    )
    monkeypatch.setattr(
        setup,
        "CLIENT_REGISTRY",
        {
            "github-copilot": {
                "name": "GitHub Copilot",
                "description": "Copilot",
                "has_auto_setup": True,
            }
        },
    )

    setup.setup_list()

    output = console.export_text()
    assert "user profile" in output
    assert "✓" in output


@pytest.mark.parametrize(
    ("client", "path_getter"),
    [
        ("claude-desktop", "_claude_desktop_profile_paths"),
        ("gemini", "_gemini_config_path"),
        ("cursor", "_cursor_config_path"),
        ("windsurf", "_windsurf_config_path"),
        ("cline", "_cline_config_path"),
        ("antigravity", "_antigravity_config_path"),
        ("opencode", "_opencode_config_path"),
    ],
)
@pytest.mark.parametrize("error_kind", ["malformed-json", "os-error"])
def test_setup_list_isolates_config_errors(tmp_path, monkeypatch, client, path_getter, error_kind):
    console = Console(record=True, width=240)
    monkeypatch.setattr(setup, "console", console)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup, "_codex_config_path", lambda: tmp_path / ".codex")
    monkeypatch.setattr(
        setup,
        "CLIENT_REGISTRY",
        {key: setup.CLIENT_REGISTRY[key] for key in (client, "claude-code", "codex")},
    )
    configured = {"mcpServers": {setup.MCP_SERVER_NAME: {"command": setup.MCP_SERVER_CMD}}}
    (tmp_path / ".claude.json").write_text(json.dumps(configured), encoding="utf-8")
    broken = tmp_path / "broken.json"
    original = '{"mcpServers": {,}'
    broken.write_text(original, encoding="utf-8")
    if client == "claude-desktop":
        healthy_profile = tmp_path / "healthy.json"
        healthy_profile.write_text(json.dumps(configured), encoding="utf-8")
        monkeypatch.setattr(setup, path_getter, lambda: {"regular": broken, "3p": healthy_profile})
    else:
        monkeypatch.setattr(setup, path_getter, lambda: broken)

    if error_kind == "os-error":
        read_config = setup._read_json_config

        def read_with_error(path):
            if path == broken:
                raise OSError("cannot read config")
            return read_config(path)

        monkeypatch.setattr(setup, "_read_json_config", read_with_error)

    setup.setup_list()

    output = console.export_text()
    broken_row = next(line for line in output.splitlines() if "broken.json" in line)
    assert setup.CLIENT_REGISTRY[client]["name"] in broken_row
    assert "?" in broken_row
    assert "✓" in next(line for line in output.splitlines() if "Claude Code" in line)
    assert "-" in next(line for line in output.splitlines() if "config.toml" in line)
    if client == "claude-desktop":
        assert "regular" in broken_row
        healthy_row = next(line for line in output.splitlines() if "healthy.json" in line)
        assert "Relay AI / 3P" in healthy_row
        assert "✓" in healthy_row
    assert broken.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("content", "expected"),
    [(b"[mcp_servers", "?"), (b"\xff", "?"), (b"", "-"), (b'model = "example"\n', "-")],
    ids=["malformed", "invalid-utf8", "empty", "unconfigured"],
)
def test_setup_list_codex_toml_status(tmp_path, monkeypatch, content, expected):
    console = Console(record=True, width=180)
    monkeypatch.setattr(setup, "console", console)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(setup, "_codex_config_path", lambda: tmp_path)
    monkeypatch.setattr(setup, "CLIENT_REGISTRY", {"codex": setup.CLIENT_REGISTRY["codex"]})
    (tmp_path / "config.toml").write_bytes(content)

    setup.setup_list()

    output = console.export_text()
    row = next(line for line in output.splitlines() if "config.toml" in line)
    assert row.split("│")[3].strip() == expected
    assert "✓" not in row
