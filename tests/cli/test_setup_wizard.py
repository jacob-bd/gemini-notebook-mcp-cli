"""Tests for the interactive guided nlm setup wizard."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput
from typer.testing import CliRunner

from notebooklm_tools.cli import main
from notebooklm_tools.cli.commands import setup, setup_wizard, skill


def test_bare_setup_noninteractive_exits_1(monkeypatch):
    monkeypatch.setattr(setup_wizard, "is_interactive", lambda: False)
    runner = CliRunner()
    result = runner.invoke(main.app, ["setup"])
    assert result.exit_code == 1
    assert (
        "interactive terminal" in result.output.lower()
        or "explicit commands" in result.output.lower()
    )


def test_setup_help_preserves_help():
    runner = CliRunner()
    result = runner.invoke(main.app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "Configure" in result.output or "setup" in result.output


def test_scan_mcp_targets_combines_codex_and_excludes_alef():
    targets = setup_wizard.scan_mcp_targets()
    ids = [t.id for t in targets]
    assert "codex" in ids
    assert "chatgpt-desktop" not in ids  # Combined into codex target
    assert "alef-agent" not in ids
    codex_target = next(t for t in targets if t.id == "codex")
    assert "Codex" in codex_target.label and "ChatGPT" in codex_target.label


def test_run_add_continues_after_one_failure(monkeypatch):
    target_cursor = setup_wizard.SetupTarget(
        "cursor", "Cursor", True, False, Path("/tmp/cursor.json"), "cursor"
    )
    target_codex = setup_wizard.SetupTarget(
        "codex", "Codex / ChatGPT", True, False, Path("/tmp/config.toml"), "agents"
    )
    monkeypatch.setattr(setup_wizard, "scan_mcp_targets", lambda: [target_cursor, target_codex])

    def mock_add(client, repair=False):
        if client == "cursor":
            raise ValueError("simulated write error")
        return True

    monkeypatch.setattr(setup_wizard, "add_one_mcp", mock_add)
    results = setup_wizard.run_add(["cursor", "codex"])
    assert len(results) == 2
    assert results[0].id == "cursor"
    assert results[0].status == "failed"
    assert "simulated write error" in results[0].message
    assert results[1].id == "codex"
    assert results[1].status == "configured"


def test_run_add_records_backups(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    target_gemini = setup_wizard.SetupTarget(
        "gemini", "Gemini CLI", True, False, Path("/tmp/gemini.json"), "agents"
    )
    monkeypatch.setattr(setup_wizard, "scan_mcp_targets", lambda: [target_gemini])

    def mock_add(client, repair=False):
        setup.backup_existing(tmp_path / "mock.json", label="gemini-backup")
        return True

    # create file to back up
    (tmp_path / "mock.json").write_text("{}")
    monkeypatch.setattr(setup_wizard, "add_one_mcp", mock_add)

    results = setup_wizard.run_add(["gemini"])
    assert len(results) == 1
    assert results[0].status == "configured"
    assert len(results[0].backup_paths) == 1
    assert results[0].backup_paths[0].name.endswith("-gemini-backup")


def test_add_one_mcp_routes_copilot_to_user_scope(monkeypatch):
    called = []
    monkeypatch.setattr(
        setup, "_setup_github_copilot", lambda scope="project": called.append(scope) or True
    )
    setup_wizard.add_one_mcp("github-copilot")
    assert called == ["user"]


def test_flow_add_passes_selected_targets_and_has_no_select_all_pseudo(monkeypatch):
    targets = [
        setup_wizard.SetupTarget(
            "cursor", "Cursor", True, False, Path("/tmp/cursor.json"), "cursor"
        ),
        setup_wizard.SetupTarget("codex", "Codex", True, False, Path("/tmp/codex.toml"), "agents"),
    ]
    monkeypatch.setattr(setup_wizard, "scan_mcp_targets", lambda: targets)
    captured_choices = []

    def fake_checkbox(prompt, *, choices, **kwargs):
        captured_choices.extend(choices)
        return SimpleNamespace(ask=lambda: ["cursor", "codex"])

    monkeypatch.setattr(setup_wizard.questionary, "checkbox", fake_checkbox)
    selected = []
    monkeypatch.setattr(setup_wizard, "run_add", lambda ids: selected.extend(ids) or [])
    monkeypatch.setattr(setup_wizard, "_flow_skill_offer", lambda selected, **kwargs: True)

    assert setup_wizard._flow_add() == 0
    # No "select all" pseudo-choice anymore (questionary's <a> key handles it)
    assert not any(getattr(choice, "value", None) == "__all__" for choice in captured_choices)
    assert selected == ["cursor", "codex"]


def test_flow_add_offers_skill_when_only_skill_capable_tools_exist(monkeypatch):
    monkeypatch.setattr(setup_wizard, "scan_mcp_targets", lambda: [])
    offers = []
    monkeypatch.setattr(
        setup_wizard,
        "_flow_skill_offer",
        lambda selected, **kwargs: offers.append(selected) or True,
    )

    assert setup_wizard._flow_add() == 0
    assert offers == [[]]


def test_flow_add_returns_cancel_status_from_skill_prompt(monkeypatch):
    monkeypatch.setattr(setup_wizard, "scan_mcp_targets", lambda: [])
    monkeypatch.setattr(
        setup_wizard.questionary,
        "confirm",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: None),
    )

    assert setup_wizard._flow_add() == 130


def test_flow_add_failed_connection_flags_skill_offer_not_ok(monkeypatch):
    """A failed connection must tell the skill offer it did NOT succeed."""
    target = setup_wizard.SetupTarget(
        "claude-desktop", "Claude Desktop", True, False, Path("/x"), None
    )
    monkeypatch.setattr(setup_wizard, "scan_mcp_targets", lambda: [target])
    monkeypatch.setattr(
        setup_wizard.questionary,
        "checkbox",
        lambda *a, **kw: SimpleNamespace(ask=lambda: ["claude-desktop"]),
    )
    monkeypatch.setattr(
        setup_wizard,
        "run_add",
        lambda ids: [
            setup_wizard.SetupResult("claude-desktop", "failed", Path("/x"), (), "Setup failed")
        ],
    )
    captured = {}
    monkeypatch.setattr(
        setup_wizard,
        "_flow_skill_offer",
        lambda selected, **kwargs: captured.update(kwargs) or True,
    )

    setup_wizard._flow_add()
    assert captured.get("connected_ok") is False


def test_skill_offer_failed_connection_prompt_is_honest(monkeypatch):
    """When the connection failed, the prompt must not claim 'Connection added'."""
    prompts = []
    monkeypatch.setattr(
        setup_wizard.questionary,
        "confirm",
        lambda prompt, **kw: prompts.append(prompt) or SimpleNamespace(ask=lambda: False),
    )

    setup_wizard._flow_skill_offer(["claude-desktop"], post_connect=True, connected_ok=False)

    assert prompts
    assert "Connection added" not in prompts[0]
    assert "didn't complete" in prompts[0]


def test_skill_offer_dedups_shared_destination(monkeypatch, tmp_path):
    destination = tmp_path / "nlm-skill"
    monkeypatch.setattr(
        skill,
        "get_skill_destination",
        lambda tool, level: destination if tool in {"agents", "antigravity"} else None,
    )
    monkeypatch.setattr(skill, "_is_tool_installed", lambda tool: tool in {"agents", "antigravity"})
    monkeypatch.setattr(setup, "_detect_tool", lambda client: False)
    monkeypatch.setattr(
        setup_wizard.questionary,
        "confirm",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: True),
    )
    monkeypatch.setattr(
        setup_wizard.questionary,
        "select",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: "Just this folder"),
    )
    choices_seen = []

    def capture_checkbox(*args, **kwargs):
        choices_seen.extend(kwargs["choices"])
        return SimpleNamespace(ask=lambda: ["agents"])

    monkeypatch.setattr(setup_wizard.questionary, "checkbox", capture_checkbox)
    installed = []
    monkeypatch.setattr(
        skill,
        "skill_action",
        lambda tool, level, action, **kwargs: (
            installed.append((tool, level))
            or skill.SkillActionResult("installed", destination, None, "Installed")
        ),
    )

    setup_wizard._flow_skill_offer([])

    # No select-all pseudo-choice; shared destination listed once (agents, not antigravity)
    assert not any(getattr(c, "value", None) == "__all__" for c in choices_seen)
    real_values = [getattr(c, "value", None) for c in choices_seen if hasattr(c, "value")]
    assert "antigravity" not in real_values
    assert installed == [("agents", "project")]


def test_skill_interrupt_summarizes_completed_install(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        skill,
        "get_skill_destination",
        lambda tool, level: tmp_path / tool if tool in {"agents", "cursor"} else None,
    )
    monkeypatch.setattr(skill, "_is_tool_installed", lambda tool: tool in {"agents", "cursor"})
    monkeypatch.setattr(setup, "_detect_tool", lambda client: False)
    monkeypatch.setattr(
        setup_wizard.questionary,
        "confirm",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: True),
    )
    monkeypatch.setattr(
        setup_wizard.questionary,
        "select",
        lambda *args, **kwargs: SimpleNamespace(
            ask=lambda: "All projects (user level) [recommended]"
        ),
    )
    monkeypatch.setattr(
        setup_wizard.questionary,
        "checkbox",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: ["agents", "cursor"]),
    )

    def install_one(tool, level, action, **kwargs):
        if tool == "cursor":
            raise KeyboardInterrupt
        return skill.SkillActionResult("installed", tmp_path / tool, None, "Installed")

    monkeypatch.setattr(skill, "skill_action", install_one)

    with pytest.raises(KeyboardInterrupt):
        setup_wizard._flow_skill_offer([])
    output = capsys.readouterr().out
    assert "Skill Setup Results" in output
    assert "agents" in output


def test_add_interrupt_summarizes_completed_target(monkeypatch, capsys):
    monkeypatch.setattr(setup_wizard, "is_interactive", lambda: True)
    monkeypatch.setattr(
        setup_wizard,
        "scan_mcp_targets",
        lambda: [
            setup_wizard.SetupTarget("cursor", "Cursor", True, False, None, "cursor"),
            setup_wizard.SetupTarget("codex", "Codex", True, False, None, "agents"),
        ],
    )
    monkeypatch.setattr(
        setup_wizard.questionary,
        "select",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: "Add the MCP to my tools/agents"),
    )
    monkeypatch.setattr(
        setup_wizard.questionary,
        "checkbox",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: ["cursor", "codex"]),
    )

    def add_one(client, *, repair=False):
        if client == "codex":
            raise KeyboardInterrupt
        return True

    monkeypatch.setattr(setup_wizard, "add_one_mcp", add_one)

    assert setup_wizard.run_setup_wizard() == 130
    output = capsys.readouterr().out
    assert "Connection Results" in output
    assert "cursor" in output


def test_copy_to_clipboard_macos(monkeypatch):
    calls = []
    monkeypatch.setattr(setup_wizard.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        setup_wizard.shutil, "which", lambda cmd: "/usr/bin/pbcopy" if cmd == "pbcopy" else None
    )
    monkeypatch.setattr(
        setup_wizard.subprocess,
        "run",
        lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert setup_wizard.copy_to_clipboard('{"test": true}') is True
    assert calls[0] == ["/usr/bin/pbcopy"]


def test_copy_to_clipboard_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(setup_wizard.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        setup_wizard.shutil, "which", lambda cmd: "C:\\Windows\\clip.exe" if cmd == "clip" else None
    )
    monkeypatch.setattr(
        setup_wizard.subprocess,
        "run",
        lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert setup_wizard.copy_to_clipboard('{"test": true}') is True
    assert calls[0] == ["C:\\Windows\\clip.exe"]


def test_copy_to_clipboard_linux_wl_copy(monkeypatch):
    calls = []
    monkeypatch.setattr(setup_wizard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        setup_wizard.shutil, "which", lambda cmd: "/usr/bin/wl-copy" if cmd == "wl-copy" else None
    )
    monkeypatch.setattr(
        setup_wizard.subprocess,
        "run",
        lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert setup_wizard.copy_to_clipboard('{"test": true}') is True
    assert calls[0] == ["wl-copy"]


def test_copy_to_clipboard_fallback_when_unavailable(monkeypatch):
    monkeypatch.setattr(setup_wizard.platform, "system", lambda: "Linux")
    monkeypatch.setattr(setup_wizard.shutil, "which", lambda cmd: None)
    assert setup_wizard.copy_to_clipboard('{"test": true}') is False


def test_questionary_none_cancellation_exits_130(monkeypatch):
    monkeypatch.setattr(setup_wizard, "is_interactive", lambda: True)
    # mock questionary select returning None (user pressed Esc or Ctrl+C)
    mock_select = MagicMock()
    mock_select.ask.return_value = None
    monkeypatch.setattr(setup_wizard.questionary, "select", lambda *a, **kw: mock_select)

    exit_code = setup_wizard.run_setup_wizard()
    assert exit_code == 130


def test_menu_loops_back_after_a_door_and_exits_on_exit(monkeypatch):
    """A finished door returns to the menu; only 'Exit' quits the wizard."""
    monkeypatch.setattr(setup_wizard, "is_interactive", lambda: True)
    # First pick a door, then choose Exit on the second menu render.
    answers = iter(["Show my tools' status", "Exit"])
    monkeypatch.setattr(
        setup_wizard.questionary,
        "select",
        lambda *a, **kw: SimpleNamespace(ask=lambda: next(answers)),
    )
    calls = []
    monkeypatch.setattr(setup_wizard, "_flow_status", lambda: calls.append("status") or 0)

    exit_code = setup_wizard.run_setup_wizard()

    assert exit_code == 0
    assert calls == ["status"]  # door ran once, then the menu re-appeared


@pytest.mark.parametrize(
    "make_question",
    [
        lambda q, inp: q.checkbox("t", choices=["a", "b"], input=inp, output=DummyOutput()),
        lambda q, inp: q.select("t", choices=["a", "b"], input=inp, output=DummyOutput()),
        # confirm has read-only merged key bindings — regression for the Esc crash.
        lambda q, inp: q.confirm("t", input=inp, output=DummyOutput()),
    ],
    ids=["checkbox", "select", "confirm"],
)
def test_ask_with_back_esc_returns_none_on_real_question(make_question):
    import questionary

    from notebooklm_tools.cli.commands.setup import ask_with_back

    with create_pipe_input() as inp:
        q = make_question(questionary, inp)
        inp.send_text("\x1b")  # lone Esc -> go back
        assert ask_with_back(q) is None


def test_ask_with_back_is_mock_safe():
    from notebooklm_tools.cli.commands.setup import ask_with_back

    # Mocked questions have no .application; the helper must still just call ask().
    q = SimpleNamespace(ask=lambda: "ok")
    assert ask_with_back(q) == "ok"


# --- Task 6: Removal Flow Tests ---


def test_scan_removable_detects_mcp_and_skills(monkeypatch, tmp_path):
    # Setup mock configs
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text('{"mcpServers": {"gemini-notebook-mcp": {"command": "notebooklm-mcp"}}}')
    monkeypatch.setattr(setup, "_cursor_config_path", lambda: cursor_file)

    skill_dir = tmp_path / "nlm-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: nlm-skill\n---\n")
    monkeypatch.setitem(skill.TOOL_CONFIGS, "agents", {"user": skill_dir, "format": "skill.md"})

    # Ensure other tools report not configured
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {})
    monkeypatch.setattr(setup, "_is_already_configured", lambda client: client == "cursor")
    monkeypatch.setattr(setup, "_is_copilot_configured", lambda scope="user": False)

    targets = setup_wizard.scan_removable()
    target_ids = [t.id for t in targets]

    assert "cursor" in target_ids
    assert "skill:agents:user" in target_ids
    agents_target = next(t for t in targets if t.id == "skill:agents:user")
    assert "Codex" in agents_target.label or "shared" in agents_target.label.lower()


def test_scan_removable_includes_every_supported_installed_skill(monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {})
    monkeypatch.setattr(setup, "_is_already_configured", lambda client: False)
    monkeypatch.setattr(setup, "_is_copilot_configured", lambda scope="user": False)

    tools = ("antigravity", "cline", "hermes", "openclaw")
    for tool in tools:
        skill_dir = tmp_path / tool / "nlm-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("---\nname: nlm-skill\n---\n")
        monkeypatch.setitem(skill.TOOL_CONFIGS, tool, {"user": skill_dir, "format": "skill.md"})

    target_ids = {target.id for target in setup_wizard.scan_removable()}

    assert {f"skill:{tool}:user" for tool in tools} <= target_ids


def test_scan_removable_claude_desktop_profiles(monkeypatch, tmp_path):
    reg_path = tmp_path / "claude_regular.json"
    reg_path.write_text('{"mcpServers": {"gemini-notebook-mcp": {"command": "notebooklm-mcp"}}}')
    relay_path = tmp_path / "claude_3p.json"
    relay_path.write_text('{"mcpServers": {"gemini-notebook-mcp": {"command": "notebooklm-mcp"}}}')

    monkeypatch.setattr(
        setup,
        "_claude_desktop_profile_paths",
        lambda: {
            "regular": reg_path,
            "3p": relay_path,
        },
    )
    monkeypatch.setattr(setup, "_is_already_configured", lambda client: False)
    monkeypatch.setattr(setup, "_is_copilot_configured", lambda scope="user": False)

    targets = setup_wizard.scan_removable()
    ids = [t.id for t in targets if t.id.startswith("claude-desktop:")]
    assert "claude-desktop:regular" in ids
    assert "claude-desktop:3p" in ids


def test_run_remove_mcp_and_skills_flow(monkeypatch, tmp_path):
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text(
        '{"mcpServers": {"gemini-notebook-mcp": {"command": "notebooklm-mcp"}, "other": {"command": "other"}}}'
    )
    monkeypatch.setattr(setup, "_cursor_config_path", lambda: cursor_file)

    skill_dir = tmp_path / "nlm-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: nlm-skill\n---\n")
    monkeypatch.setitem(skill.TOOL_CONFIGS, "agents", {"user": skill_dir, "format": "skill.md"})

    monkeypatch.setattr(setup, "_is_already_configured", lambda c: c == "cursor")
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {})
    monkeypatch.setattr(setup, "_is_copilot_configured", lambda s="user": False)

    # User confirms both MCP removal and skill folder deletion
    mock_confirm = MagicMock()
    mock_confirm.ask.side_effect = [True, True]
    monkeypatch.setattr(setup_wizard.questionary, "confirm", lambda *a, **kw: mock_confirm)

    results = setup_wizard.run_remove(["cursor", "skill:agents:user"])
    assert len(results) == 2
    cursor_res = next(r for r in results if r.id == "cursor")
    skill_res = next(r for r in results if r.id == "skill:agents:user")

    assert cursor_res.status == "removed"
    assert skill_res.status == "removed"
    assert not skill_dir.exists()
    # Unrelated MCP is preserved
    import json

    updated = json.loads(cursor_file.read_text())
    assert "other" in updated["mcpServers"]
    assert "gemini-notebook-mcp" not in updated["mcpServers"]


def test_run_remove_cancellation_default_no(monkeypatch, tmp_path):
    cursor_file = tmp_path / "cursor.json"
    cursor_file.write_text('{"mcpServers": {"gemini-notebook-mcp": {"command": "notebooklm-mcp"}}}')
    monkeypatch.setattr(setup, "_cursor_config_path", lambda: cursor_file)

    skill_dir = tmp_path / "nlm-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: nlm-skill\n---\n")
    monkeypatch.setitem(skill.TOOL_CONFIGS, "agents", {"user": skill_dir, "format": "skill.md"})

    monkeypatch.setattr(setup, "_is_already_configured", lambda c: c == "cursor")
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {})
    monkeypatch.setattr(setup, "_is_copilot_configured", lambda s="user": False)

    # User declines both MCP and skill deletions (default No)
    mock_confirm = MagicMock()
    mock_confirm.ask.side_effect = [False, False]
    monkeypatch.setattr(setup_wizard.questionary, "confirm", lambda *a, **kw: mock_confirm)

    results = setup_wizard.run_remove(["cursor", "skill:agents:user"])
    assert len(results) == 2
    assert all(r.status == "skipped" for r in results)
    assert all(r.message == "Cancelled" for r in results)
    assert skill_dir.exists()
    assert "gemini-notebook-mcp" in cursor_file.read_text()


def test_remove_copilot_jsonc_refusal(monkeypatch, tmp_path):
    copilot_file = tmp_path / "mcp.json"
    copilot_file.write_text(
        """// VS Code MCP settings\n{\n  "servers": {\n    "gemini-notebook-mcp": {\n      "command": "notebooklm-mcp"\n    }\n  }\n}"""
    )
    monkeypatch.setattr(setup, "_github_copilot_config_path", lambda scope="user": copilot_file)
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {})
    monkeypatch.setattr(setup, "_is_already_configured", lambda c: False)

    target = setup_wizard.SetupTarget(
        "github-copilot:user", "GitHub Copilot (user)", True, True, copilot_file, None
    )
    results = setup_wizard.remove_mcp_targets([target])
    assert len(results) == 1
    assert results[0].status == "failed"
    # Content must NOT be modified or comment stripped
    assert "// VS Code MCP settings" in copilot_file.read_text()


def test_remove_codex_desktop_only(monkeypatch, tmp_path):
    codex_toml = tmp_path / "config.toml"
    codex_toml.write_text("""
model = "o3"

[mcp_servers.gemini-notebook-mcp]
command = "/path/to/notebooklm-mcp"
tool_timeout_sec = 300

[mcp_servers.other]
command = "other"
""")
    monkeypatch.setattr(setup, "_codex_config_path", lambda: tmp_path)
    monkeypatch.setattr(setup.shutil, "which", lambda cmd: None)  # No codex in PATH

    target = setup_wizard.SetupTarget(
        "codex", "Codex / ChatGPT desktop", True, True, codex_toml, None
    )
    results = setup_wizard.remove_mcp_targets([target])
    assert len(results) == 1
    assert results[0].status == "removed"
    updated = codex_toml.read_text()
    assert "gemini-notebook-mcp" not in updated
    assert "other" in updated
    assert 'model = "o3"' in updated


def test_remove_backup_failure_keeps_skill(monkeypatch, tmp_path):
    skill_dir = tmp_path / "nlm-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: nlm-skill\n---\n")
    monkeypatch.setitem(skill.TOOL_CONFIGS, "agents", {"user": skill_dir, "format": "skill.md"})
    monkeypatch.setattr(
        skill,
        "backup_existing",
        lambda *a, **kw: (_ for _ in ()).throw(PermissionError("backup denied")),
    )
    result = skill.skill_action("agents", "user", "remove", confirm_replace=lambda _: True)
    assert result.status == "failed"
    assert (skill_dir / "SKILL.md").exists()


def test_flow_remove_ctrl_c_returns_130_with_partial_summary(monkeypatch, tmp_path, capsys):
    target1 = setup_wizard.SetupTarget("tool1", "Tool 1", True, True, tmp_path / "1", None)
    target2 = setup_wizard.SetupTarget("tool2", "Tool 2", True, True, tmp_path / "2", None)
    monkeypatch.setattr(setup_wizard, "scan_removable", lambda: [target1, target2])
    monkeypatch.setattr(
        setup_wizard.questionary,
        "checkbox",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: ["tool1", "tool2"]),
    )
    monkeypatch.setattr(
        setup_wizard.questionary,
        "confirm",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: True),
    )
    removed = []

    def remove_one(client, **kwargs):
        if client == "tool2":
            raise KeyboardInterrupt
        removed.append(client)
        return True

    monkeypatch.setattr(setup, "_remove_single", remove_one)

    exit_code = setup_wizard._flow_remove()
    assert exit_code == 130
    assert removed == ["tool1"]
    output = capsys.readouterr().out
    assert "Removal Results" in output
    assert "tool1" in output


def test_flow_remove_selects_only_exact_target_id(monkeypatch, tmp_path):
    targets = [
        setup_wizard.SetupTarget(
            "skill:tool:user", "NLM Skill", True, True, tmp_path / "one", "tool"
        ),
        setup_wizard.SetupTarget(
            "skill:extra:user", "NLM Skill Extra", True, True, tmp_path / "two", "extra"
        ),
    ]
    monkeypatch.setattr(setup_wizard, "scan_removable", lambda: targets)
    monkeypatch.setattr(
        setup_wizard.questionary,
        "checkbox",
        lambda *args, **kwargs: SimpleNamespace(ask=lambda: ["skill:extra:user"]),
    )
    selected = []
    monkeypatch.setattr(setup_wizard, "run_remove", lambda ids: selected.extend(ids) or [])

    assert setup_wizard._flow_remove() == 0
    assert selected == ["skill:extra:user"]


def test_build_connect_rows_groups_and_hides_paths():
    targets = [
        setup_wizard.SetupTarget(
            "codex",
            "Codex / ChatGPT",
            True,
            True,
            Path("/x"),
            "agents",
            repair_reason="tool_timeout_sec (None) is below 300",
        ),
        setup_wizard.SetupTarget("windsurf", "Windsurf", True, False, Path("/y"), None),
        setup_wizard.SetupTarget("cursor", "Cursor", True, True, Path("/z"), "cursor"),
    ]
    rows = setup_wizard.build_connect_rows(targets)
    by_value = {r.value: r for r in rows}
    assert by_value["codex"].group == "Needs a fix"
    # Connect picker is opt-in: nothing pre-ticked (user chooses explicitly).
    assert by_value["codex"].checked is False
    assert "quick fix" in by_value["codex"].note
    assert "/x" not in by_value["codex"].label
    assert "300" not in by_value["codex"].label
    assert by_value["windsurf"].group == "Not connected yet"
    assert by_value["windsurf"].checked is False
    assert by_value["cursor"].group == "Already connected"
    assert by_value["cursor"].disabled == "already connected"
    assert by_value["cursor"].checked is False


def test_results_summary_has_no_path_dump(capsys):
    results = [
        setup_wizard.SetupResult(
            "codex",
            "configured",
            Path("/Users/me/.codex/config.toml"),
            (Path("/Users/me/.codex/config.toml.bak"),),
            "Configured",
        )
    ]
    setup_wizard._display_results_summary("Connection Results", results)
    out = capsys.readouterr().out
    assert "Backup for" not in out
    assert "config.toml.bak" not in out
    assert "backed up" in out.lower()


def test_build_skill_rows_flags_upgrade_and_shared(monkeypatch):
    monkeypatch.setattr(skill, "get_skill_destination", lambda t, level: Path(f"/skills/{t}"))
    monkeypatch.setattr(setup_wizard.setup, "_detect_tool", lambda k: True)
    monkeypatch.setattr(skill, "_is_tool_installed", lambda t: True)
    states = {
        "agents": {
            "supported": True,
            "installed": True,
            "version": "0.0.1",
            "package_version": "9.9.9",
            "upgrade_available": True,
        },
        "claude-code": {
            "supported": True,
            "installed": True,
            "version": "9.9.9",
            "package_version": "9.9.9",
            "upgrade_available": False,
        },
    }
    default = {
        "supported": True,
        "installed": False,
        "version": None,
        "package_version": "9.9.9",
        "upgrade_available": False,
    }
    monkeypatch.setattr(skill, "skill_version_state", lambda t, level: states.get(t, default))
    options = [
        ("agents", "Agents / Codex / ChatGPT / Gemini CLI", ["codex", "gemini"]),
        ("claude-code", "Claude Code CLI", ["claude-code"]),
    ]
    rows = setup_wizard.build_skill_rows(options, "user", selected_mcp_ids=[])
    by_value = {r.value: r for r in rows}
    assert "shared file" in by_value["agents"].label
    assert "upgrade available" in (by_value["agents"].note or "")
    assert by_value["agents"].checked is True
    assert "installed" in (by_value["claude-code"].note or "")
    assert by_value["claude-code"].checked is False
    # no full path in the label
    assert "/skills/" not in by_value["agents"].label


def test_build_remove_rows_groups_and_opts_in(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    targets = [
        setup_wizard.SetupTarget(
            "cursor", "Cursor", True, True, tmp_path / ".cursor/mcp.json", "cursor"
        ),
        setup_wizard.SetupTarget(
            "skill:agents:user",
            "nlm-skill (shared) [user]",
            True,
            True,
            tmp_path / ".codex/skill",
            "agents",
        ),
    ]
    rows = setup_wizard.build_remove_rows(targets)
    by_value = {r.value: r for r in rows}
    assert by_value["cursor"].group == "MCP connections"
    assert by_value["cursor"].checked is False
    assert by_value["cursor"].note.startswith("~")
    assert by_value["skill:agents:user"].group == "Skills"
    assert by_value["skill:agents:user"].checked is False


def test_gemini_target_skill_id_resolves_to_shared_skill():
    targets = {t.id: t for t in setup_wizard.scan_mcp_targets()}
    gemini = targets["gemini"]
    # Gemini CLI shares the "agents" skill file; its skill_id must resolve, not be n/a.
    assert gemini.skill_id is not None
    assert skill.get_skill_destination(gemini.skill_id, "user") is not None


def test_skill_rows_always_offer_upload_row_unticked():
    rows = setup_wizard.with_upload_row([])
    assert rows[-1].value == setup_wizard.UPLOAD_ROW_VALUE
    assert rows[-1].checked is False
    assert "Claude Desktop / claude.ai" in rows[-1].label


def test_claude_desktop_profiles_are_separate_wizard_rows(monkeypatch, tmp_path):
    from notebooklm_tools.cli.commands import setup, setup_wizard

    regular, threep = tmp_path / "r.json", tmp_path / "t.json"
    regular.write_text('{"mcpServers": {"gemini-notebook-mcp": {"command": "x"}}}')
    threep.write_text("{}")
    monkeypatch.setattr(
        setup, "_claude_desktop_profile_paths", lambda: {"regular": regular, "3p": threep}
    )
    rows = {t.id: t for t in setup_wizard._claude_desktop_targets()}
    assert rows["claude-desktop:regular"].configured is True
    assert rows["claude-desktop:3p"].configured is False
    assert "Relay" in rows["claude-desktop:3p"].label


def test_add_one_mcp_3p_row_targets_only_3p_and_waits_for_quit(monkeypatch, tmp_path):
    from notebooklm_tools.cli.commands import setup, setup_wizard

    path = tmp_path / "t.json"
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {"3p": path})
    monkeypatch.setattr(setup_wizard, "_wait_for_claude_desktop_to_quit", lambda *a: True)
    calls = []
    monkeypatch.setattr(
        setup, "_setup_claude_desktop", lambda profile=None: calls.append(profile) or True
    )
    assert setup_wizard.add_one_mcp("claude-desktop:3p") is True
    assert calls == ["3p"]


def test_add_one_mcp_skip_when_user_declines_to_quit(monkeypatch, tmp_path):
    import pytest

    from notebooklm_tools.cli.commands import setup, setup_wizard

    path = tmp_path / "t.json"
    monkeypatch.setattr(setup, "_claude_desktop_profile_paths", lambda: {"3p": path})
    monkeypatch.setattr(setup_wizard, "_wait_for_claude_desktop_to_quit", lambda *a: False)
    with pytest.raises(setup_wizard._BackRequested):
        setup_wizard.add_one_mcp("claude-desktop:3p")
