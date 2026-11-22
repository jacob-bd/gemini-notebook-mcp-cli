"""End-to-end tests: drive the real `nlm setup` wizard in a pseudo-terminal.

Opt-in (slow): run with `uv run pytest -m wizard_e2e` after changing the setup
wizard, setup.py or skill.py.

Each test runs the actual wizard subprocess against a sandboxed HOME with fake
tool binaries (see wizard_driver.py), presses real keys, then checks both what
the screen shows and what the wizard actually wrote to disk.
"""

import json
import re
import sys
import zipfile

import pytest

pytestmark = [
    pytest.mark.wizard_e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX pseudo-terminal"),
    pytest.mark.skipif(sys.platform != "darwin", reason="sandbox paths model macOS layouts"),
]

pexpect = pytest.importorskip("pexpect")
pytest.importorskip("pyte")

from wizard_driver import ENTER, SERVER_BIN, Sandbox, Wizard  # noqa: E402

from notebooklm_tools import __version__  # noqa: E402

MENU = "What would you like to do"
CONNECT = "Select which tools to connect"
SKILL_PICK = "Add the skill to which tools"
REMOVE = "Select what to remove"


@pytest.fixture
def sandbox(tmp_path):
    sb = Sandbox(tmp_path)
    sb.extra_env["PROMPT_TOOLKIT_NO_CPR"] = "1"
    return sb


@pytest.fixture
def run(sandbox):
    """Start the wizard; always kill it at the end of the test."""
    started: list[Wizard] = []

    def _start() -> Wizard:
        w = Wizard(sandbox)
        started.append(w)
        w.expect(MENU)
        w.settle()
        return w

    yield _start
    for w in started:
        w.close()


def _connect(w: Wizard, *labels: str) -> None:
    w.choose(MENU, "Add the MCP")
    w.expect(CONNECT)
    w.pick(CONNECT, *labels)


def _skill_scope(w: Wizard, scope: str = "All my projects") -> None:
    w.expect("Where should the skill live")
    w.choose("Where should the skill live", scope)
    w.expect(SKILL_PICK)
    w.settle()


def _set_skill_version(path, version: str) -> None:
    text = path.read_text()
    path.write_text(re.sub(r'version: "[^"]+"', f'version: "{version}"', text, count=1))


# --- main menu -----------------------------------------------------------------


def test_exit_option_quits_cleanly(run):
    w = run()
    assert w.quit() == 0


def test_esc_on_main_menu_quits(run):
    w = run()
    w.esc()
    assert w.finish() == 130


# --- Add the MCP ---------------------------------------------------------------


def test_connect_picker_is_opt_in_and_lists_detected_tools(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    w = run()
    w.choose(MENU, "Add the MCP")
    w.expect(CONNECT)
    w.settle()

    rows = w.choice_lines(CONNECT)
    assert any("Codex" in r for r in rows)
    assert any("Claude Code" in r for r in rows)
    assert not any("Cursor" in r for r in rows)  # not installed -> not offered
    assert w.ticked(CONNECT) == []  # nothing pre-selected


def test_esc_on_connect_picker_returns_to_menu(sandbox, run):
    sandbox.install_codex()
    w = run()
    w.choose(MENU, "Add the MCP")
    w.expect(CONNECT)
    w.settle()
    w.esc()
    w.expect(MENU)
    assert w.quit() == 0
    assert sandbox.codex_toml == ""


def test_connect_writes_every_selected_tool(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    sandbox.install_claude_desktop()
    sandbox.install_cursor()
    w = run()
    _connect(w, "Codex", "Claude Code", "Claude Desktop", "Cursor")
    w.expect("Connection added. Also add the skill")
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0

    expected = {"command": SERVER_BIN}
    assert sandbox.claude_json["mcpServers"]["gemini-notebook-mcp"] == expected
    assert sandbox.claude_desktop_config()["mcpServers"]["gemini-notebook-mcp"]["command"] == (
        SERVER_BIN
    )
    assert sandbox.cursor_config["mcpServers"]["gemini-notebook-mcp"]["command"] == SERVER_BIN
    assert "[mcp_servers.gemini-notebook-mcp]" in sandbox.codex_toml
    assert f'command = "{SERVER_BIN}"' in sandbox.codex_toml
    assert "tool_timeout_sec = 300" in sandbox.codex_toml


def test_already_connected_tools_are_shown_but_not_selectable(sandbox, run):
    sandbox.install_codex()
    sandbox.install_cursor()
    w = run()
    _connect(w, "Codex")
    w.expect("Also add the skill")
    w.send("n")
    w.expect(MENU)
    w.settle()

    w.choose(MENU, "Add the MCP")
    w.expect(CONNECT)
    w.settle()
    text = "\n".join(w.choice_lines(CONNECT))
    assert "Already connected" in text
    assert re.search(r"Codex.*already connected", text)
    # The pointer skips the disabled row and starts on Cursor.
    assert "Cursor" in w.pointed(CONNECT)


def test_enter_with_nothing_ticked_connects_nothing(sandbox, run):
    sandbox.install_codex()
    w = run()
    w.choose(MENU, "Add the MCP")
    w.expect(CONNECT)
    w.settle()
    w.send(ENTER)
    w.expect("No tools selected")
    w.expect(r"Add the skill\? \(recommended\)")
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    assert sandbox.codex_toml == ""


def test_failed_connection_is_reported_honestly(sandbox, run):
    sandbox.install_claude_code()
    sandbox.extra_env["WIZ_CLAUDE_FAIL"] = "1"
    w = run()
    _connect(w, "Claude Code")
    w.expect("failed")
    w.expect("The connection didn't complete. Add the skill anyway")
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    assert sandbox.claude_json == {}


def test_esc_on_post_connect_skill_question_returns_to_menu(sandbox, run):
    sandbox.install_codex()
    w = run()
    _connect(w, "Codex")
    w.expect("Also add the skill")
    w.settle()
    w.esc()
    w.expect(MENU)
    assert w.quit() == 0
    assert "gemini-notebook-mcp" in sandbox.codex_toml  # the connection itself stays


def test_claude_desktop_profiles_are_separate_rows(sandbox, run):
    sandbox.install_claude_desktop(profiles=("Claude", "Claude-3p"))
    w = run()
    _connect(w, "Claude Desktop (subscription)", "Claude Desktop (Relay AI / 3P)")
    w.expect("Also add the skill")
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    for profile in ("Claude", "Claude-3p"):
        cfg = sandbox.claude_desktop_config(profile)
        assert cfg["mcpServers"]["gemini-notebook-mcp"]["command"] == SERVER_BIN


def test_claude_desktop_3p_row_only_writes_3p(sandbox, run):
    sandbox.install_claude_desktop(profiles=("Claude", "Claude-3p"))
    w = run()
    _connect(w, "Claude Desktop (Relay AI / 3P)")
    w.expect("Also add the skill")
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    cfg = sandbox.claude_desktop_config("Claude-3p")
    assert cfg["mcpServers"]["gemini-notebook-mcp"]["command"] == SERVER_BIN
    assert sandbox.claude_desktop_config("Claude") == {}


def test_claude_desktop_running_offers_to_quit_and_can_be_skipped(sandbox, run):
    sandbox.install_claude_desktop()
    sandbox.extra_env["WIZ_CLAUDE_DESKTOP_RUNNING"] = "1"
    w = run()
    _connect(w, "Claude Desktop (subscription)")
    w.expect("is running. Quit it completely")
    w.choose("is running. Quit it completely", "Skip this one")
    w.expect("Connection Results")
    w.expect("didn't complete")
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    assert sandbox.claude_desktop_config() == {}


# --- skill (after connect and standalone) -----------------------------------------


def test_connect_then_skill_pre_ticks_connected_tools_and_installs(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    sandbox.install_cursor()
    w = run()
    _connect(w, "Codex", "Claude Code")
    w.expect("Connection added. Also add the skill")
    w.send(ENTER)  # default: yes
    _skill_scope(w)

    ticked = "\n".join(w.ticked(SKILL_PICK))
    assert "Agents / Codex" in ticked
    assert "Claude Code" in ticked
    assert "Cursor" not in ticked  # installed, but not connected just now

    w.send(ENTER)
    w.expect("Skill Setup Results")
    w.expect(MENU)
    assert w.quit() == 0
    assert (sandbox.home / ".agents/skills/nlm-skill/SKILL.md").exists()
    assert (sandbox.home / ".claude/skills/nlm-skill/SKILL.md").exists()
    assert not (sandbox.home / ".cursor/skills/nlm-skill").exists()


def test_skill_door_project_scope_installs_into_current_folder(sandbox, run):
    sandbox.install_claude_code()
    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w, "Just this folder")
    w.pick(SKILL_PICK, "Claude Code")
    w.expect("Skill Setup Results")
    w.expect(MENU)
    assert w.quit() == 0
    assert (sandbox.project / ".claude/skills/nlm-skill/SKILL.md").exists()
    assert not (sandbox.home / ".claude/skills/nlm-skill").exists()


@pytest.mark.parametrize("where", ["scope", "picker"])
def test_esc_inside_skill_door_returns_to_menu(sandbox, run, where):
    sandbox.install_claude_code()
    w = run()
    w.choose(MENU, "Add the skill")
    w.expect("Where should the skill live")
    w.settle()
    if where == "picker":
        w.send(ENTER)
        w.expect(SKILL_PICK)
        w.settle()
    w.esc()
    w.expect(MENU)
    assert w.quit() == 0
    assert not (sandbox.home / ".claude/skills/nlm-skill").exists()


def test_skill_upgrade_is_flagged_pre_ticked_and_replaces_old_version(sandbox, run):
    sandbox.install_claude_code()
    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w)
    w.pick(SKILL_PICK, "Claude Code")
    w.expect(MENU)
    assert w.quit() == 0

    skill_md = sandbox.home / ".claude/skills/nlm-skill/SKILL.md"
    _set_skill_version(skill_md, "0.0.1")

    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w)
    row = "\n".join(w.ticked(SKILL_PICK))
    assert "Claude Code" in row and "upgrade available" in row

    w.send(ENTER)
    w.expect(rf"(?s)Replace v0\.0\.1 skill .* with v{re.escape(__version__)}")
    w.send("y")
    w.expect("Skill Setup Results")
    w.expect(MENU)
    assert w.quit() == 0
    assert f'version: "{__version__}"' in skill_md.read_text()


def test_esc_on_skill_replace_question_returns_to_menu(sandbox, run):
    sandbox.install_claude_code()
    skill_md = sandbox.home / ".claude/skills/nlm-skill/SKILL.md"
    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w)
    w.pick(SKILL_PICK, "Claude Code")
    w.expect(MENU)
    assert w.quit() == 0
    _set_skill_version(skill_md, "0.0.1")

    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w)
    w.send(ENTER)
    w.expect("Replace v0.0.1 skill")
    w.settle()
    w.esc()
    w.expect(MENU)
    assert w.quit() == 0
    assert 'version: "0.0.1"' in skill_md.read_text()  # untouched


# --- status ----------------------------------------------------------------------


def test_status_shows_connection_and_skill_state(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    w = run()
    _connect(w, "Codex")
    w.expect("Also add the skill")
    w.send("n")
    w.expect(MENU)
    w.settle()

    w.choose(MENU, "Show my tools")
    w.expect("Only tools found on your machine are shown")
    w.settle()
    text = w.text()
    assert re.search(r"Codex.*✓ set up.*✗ not yet", text)
    assert re.search(r"Claude Code.*✗ not yet.*✗ not yet", text)
    w.expect(MENU)
    assert w.quit() == 0


# --- remove ----------------------------------------------------------------------


def _connect_codex_and_claude_skill(w: Wizard) -> None:
    _connect(w, "Codex", "Claude Code")
    w.expect("Also add the skill")
    w.send(ENTER)
    _skill_scope(w)
    w.send(ENTER)  # accept the pre-ticked skill rows
    w.expect("Skill Setup Results")
    w.expect(MENU)
    w.settle()


def test_remove_lists_grouped_items_with_nothing_ticked(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    w = run()
    _connect_codex_and_claude_skill(w)

    w.choose(MENU, "Remove")
    w.expect(REMOVE)
    w.settle()
    text = "\n".join(w.choice_lines(REMOVE))
    assert "MCP connections" in text and "Skills" in text
    assert text.index("MCP connections") < text.index("Codex") < text.index("Skills")
    assert "nlm-skill (Claude Code) [user]" in text
    assert w.ticked(REMOVE) == []


def test_remove_mcp_and_skill_after_two_confirms(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    w = run()
    _connect_codex_and_claude_skill(w)

    w.choose(MENU, "Remove")
    w.expect(REMOVE)
    w.pick(REMOVE, "Codex", "nlm-skill (Claude Code)")
    w.expect("Remove the selected MCP entries")
    w.send("y")
    w.expect("Delete the listed skill folders")
    w.send("y")
    w.expect("Removal Results")
    w.expect(MENU)
    assert w.quit() == 0

    assert "gemini-notebook-mcp" not in sandbox.codex_toml
    assert not (sandbox.home / ".claude/skills/nlm-skill").exists()
    # Not selected -> kept.
    assert "gemini-notebook-mcp" in sandbox.claude_json["mcpServers"]
    assert (sandbox.home / ".agents/skills/nlm-skill/SKILL.md").exists()


def test_remove_declined_keeps_everything(sandbox, run):
    sandbox.install_claude_code()
    sandbox.install_codex()
    w = run()
    _connect_codex_and_claude_skill(w)

    w.choose(MENU, "Remove")
    w.expect(REMOVE)
    w.pick(REMOVE, "Codex", "nlm-skill (Claude Code)")
    w.expect("Remove the selected MCP entries")
    w.send(ENTER)  # default: no
    w.expect("Delete the listed skill folders")
    w.send(ENTER)  # default: no
    w.expect("Removal Results")
    w.expect(MENU)
    assert w.quit() == 0
    assert "gemini-notebook-mcp" in sandbox.codex_toml
    assert (sandbox.home / ".claude/skills/nlm-skill/SKILL.md").exists()


@pytest.mark.parametrize("where", ["picker", "confirm"])
def test_esc_inside_remove_returns_to_menu_and_keeps_everything(sandbox, run, where):
    sandbox.install_claude_code()
    sandbox.install_codex()
    w = run()
    _connect_codex_and_claude_skill(w)

    w.choose(MENU, "Remove")
    w.expect(REMOVE)
    w.settle()
    if where == "confirm":
        w.pick(REMOVE, "Codex")
        w.expect("Remove the selected MCP entries")
        w.settle()
    w.esc()
    w.expect(MENU)
    assert w.quit() == 0
    assert "gemini-notebook-mcp" in sandbox.codex_toml


def test_remove_with_nothing_installed_says_so(run):
    w = run()
    w.choose(MENU, "Remove")
    w.expect("No Gemini Notebook MCP entries or skills found to remove")
    w.expect(MENU)
    assert w.quit() == 0


# --- copy MCP setup ------------------------------------------------------------


def test_copy_json_default_snippet_uses_full_path(sandbox, run):
    w = run()
    w.choose(MENU, "Copy MCP setup")
    w.expect("Copied to clipboard")
    w.expect("Need a different format")
    w.choose("Need a different format", "No, I'm done")
    w.expect(MENU)
    assert w.quit() == 0
    snippet = json.loads(sandbox.clipboard.read_text())
    assert snippet == {"mcpServers": {"gemini-notebook-mcp": {"command": SERVER_BIN}}}


def test_copy_json_advanced_uvx_entry_only(sandbox, run):
    w = run()
    w.choose(MENU, "Copy MCP setup")
    w.expect("Need a different format")
    w.choose("Need a different format", "Advanced options")
    w.expect("Command style")
    w.choose("Command style", "uvx")
    w.expect("Snippet shape")
    w.choose("Snippet shape", "Server entry only")
    w.expect("Copied to clipboard")
    w.expect(MENU)
    assert w.quit() == 0
    snippet = json.loads(sandbox.clipboard.read_text())
    assert snippet == {
        "gemini-notebook-mcp": {
            "command": "uvx",
            "args": ["--from", "notebooklm-mcp-cli", "notebooklm-mcp"],
        }
    }


def test_copy_json_advanced_bare_command(sandbox, run):
    w = run()
    w.choose(MENU, "Copy MCP setup")
    w.expect("Need a different format")
    w.choose("Need a different format", "Advanced options")
    w.expect("Command style")
    w.choose("Command style", "Installed binary")
    w.expect("Path style")
    w.choose("Path style", "Just the command name")
    w.expect("Snippet shape")
    w.choose("Snippet shape", "Full config file")
    w.expect("Copied to clipboard")
    w.expect(MENU)
    assert w.quit() == 0
    snippet = json.loads(sandbox.clipboard.read_text())
    assert snippet == {"mcpServers": {"gemini-notebook-mcp": {"command": "notebooklm-mcp"}}}


@pytest.mark.parametrize("where", ["format", "style", "path", "shape"])
def test_esc_inside_copy_json_returns_to_menu(run, where):
    w = run()
    w.choose(MENU, "Copy MCP setup")
    w.expect("Need a different format")
    w.settle()
    if where != "format":
        w.choose("Need a different format", "Advanced options")
        w.expect("Command style")
        w.settle()
        if where in ("path", "shape"):
            w.choose("Command style", "Installed binary")
            w.expect("Path style")
            w.settle()
            if where == "shape":
                w.choose("Path style", "Full path")
                w.expect("Snippet shape")
                w.settle()
    w.esc()
    w.expect(MENU)
    assert w.quit() == 0


def test_esc_on_claude_desktop_quit_prompt_skips_only_that_tool(sandbox, run):
    sandbox.install_claude_desktop()
    sandbox.install_codex()
    sandbox.extra_env["WIZ_CLAUDE_DESKTOP_RUNNING"] = "1"
    w = run()
    _connect(w, "Codex", "Claude Desktop (subscription)")
    w.expect("is running. Quit it completely")
    w.settle()
    w.esc()
    w.expect("Connection Results")
    w.expect("Also add the skill")
    w.settle()
    assert re.search(r"claude-desktop.*skipped", w.text())
    assert not re.search(r"claude-desktop.*failed", w.text())
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    assert "gemini-notebook-mcp" in sandbox.codex_toml  # the other tool still connected
    assert sandbox.claude_desktop_config() == {}


# --- entries still using the old name ---------------------------------------------


def _seed_old_names(sandbox) -> None:
    """Tools connected under the pre-rebrand name `notebooklm-mcp`, with extra settings."""
    sandbox.install_claude_code()
    sandbox.install_codex()
    sandbox.install_cursor()
    old = {"type": "stdio", "command": "notebooklm-mcp", "args": [], "env": {"X": "1"}}
    (sandbox.home / ".claude.json").write_text(
        json.dumps({"mcpServers": {"notebooklm-mcp": old, "other": {"command": "o"}}})
    )
    (sandbox.home / ".codex" / "config.toml").write_text(
        'model = "o3"\n\n'
        "[mcp_servers.notebooklm-mcp]\n"
        f'command = "{SERVER_BIN}"\n'
        "enabled = true\n"
        "tool_timeout_sec = 300\n\n"
        "[mcp_servers.other]\n"
        'command = "other"\n'
    )
    (sandbox.home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"notebooklm-mcp": {"command": SERVER_BIN, "args": []}}})
    )


def test_status_flags_old_names(sandbox, run):
    _seed_old_names(sandbox)
    w = run()
    w.choose(MENU, "Show my tools")
    w.expect("Only tools found on your machine are shown")
    w.expect("to fix it")
    w.settle()
    text = w.text()
    for tool in ("Codex", "Claude Code", "Cursor"):
        assert re.search(rf"{tool}.*⚠ old name", text), tool


def test_connect_offers_and_performs_the_rename(sandbox, run):
    _seed_old_names(sandbox)
    w = run()
    w.choose(MENU, "Add the MCP")
    w.expect(CONNECT)
    w.settle()
    rows = "\n".join(w.choice_lines(CONNECT))
    assert "Needs a fix" in rows
    for tool in ("Codex", "Claude Code", "Cursor"):
        assert re.search(rf"{tool}.*uses the old name", rows), tool
    assert w.ticked(CONNECT) == []

    w.pick(CONNECT, "Codex", "Claude Code", "Cursor")
    w.expect("Connection Results")
    w.expect("Also add the skill")
    w.settle()
    assert len(re.findall(r"repaired.*Renamed to gemini-notebook-mcp", w.text())) == 3
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0

    claude = sandbox.claude_json["mcpServers"]
    assert "notebooklm-mcp" not in claude
    assert claude["gemini-notebook-mcp"]["env"] == {"X": "1"}  # settings kept
    assert claude["other"] == {"command": "o"}  # unrelated entry untouched

    toml = sandbox.codex_toml
    assert "[mcp_servers.notebooklm-mcp]" not in toml
    assert "[mcp_servers.gemini-notebook-mcp]" in toml
    assert "enabled = true" in toml  # settings kept
    assert "[mcp_servers.other]" in toml

    cursor = sandbox.cursor_config["mcpServers"]
    assert list(cursor) == ["gemini-notebook-mcp"]

    # A second look shows them as plain "set up" now.
    w = run()
    w.choose(MENU, "Show my tools")
    w.expect("Only tools found on your machine are shown")
    w.settle()
    assert "old name" not in w.text()


def test_failed_claude_code_rename_keeps_old_entry_and_says_failed(sandbox, run):
    _seed_old_names(sandbox)
    sandbox.extra_env["WIZ_CLAUDE_FAIL"] = "1"
    w = run()
    _connect(w, "Claude Code")
    w.expect("Connection Results")
    w.expect("didn't complete")
    w.settle()
    assert re.search(r"claude-code.*failed", w.text())
    assert "Renamed" not in w.text()
    w.send("n")
    w.expect(MENU)
    assert w.quit() == 0
    assert "notebooklm-mcp" in sandbox.claude_json["mcpServers"]


# --- Claude Desktop / claude.ai upload file -----------------------------------------


def test_skill_upload_row_creates_zip_and_explains_upload(sandbox, run):
    sandbox.install_claude_code()
    (sandbox.home / "Downloads").mkdir()
    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w)
    rows = "\n".join(w.choice_lines(SKILL_PICK))
    assert "Claude Desktop / claude.ai" in rows
    assert not any("Claude Desktop" in r for r in w.ticked(SKILL_PICK))
    w.pick(SKILL_PICK, "Claude Desktop / claude.ai")
    w.expect("Customize → Skills → Add")
    w.expect(MENU)
    assert w.quit() == 0
    zip_path = sandbox.home / "Downloads" / "nlm-skill.zip"
    with zipfile.ZipFile(zip_path) as zf:
        assert "nlm-skill/SKILL.md" in zf.namelist()
    assert any(c.startswith("open -R") for c in sandbox.shim_calls)
    assert not (sandbox.home / ".claude/skills/nlm-skill").exists()  # not ticked


def test_upload_row_with_project_scope_still_goes_to_downloads(sandbox, run):
    sandbox.install_claude_code()
    (sandbox.home / "Downloads").mkdir()
    w = run()
    w.choose(MENU, "Add the skill")
    _skill_scope(w, "Just this folder")
    w.pick(SKILL_PICK, "Claude Code", "Claude Desktop / claude.ai")
    w.expect("Customize → Skills → Add")
    w.expect(MENU)
    assert w.quit() == 0
    assert (sandbox.home / "Downloads" / "nlm-skill.zip").exists()
    assert (sandbox.project / ".claude/skills/nlm-skill/SKILL.md").exists()


def test_skill_door_goes_straight_to_choices(run):
    w = run()
    w.choose(MENU, "Add the skill")
    w.expect("Where should the skill live")
    assert "Add the skill?" not in w.plain_output()


# --- credential protection door ------------------------------------------------


def _seed_plain_login(sandbox, name="default"):
    import json

    root = sandbox.home / ".notebooklm-mcp-cli"
    prof = root / "profiles" / name
    prof.mkdir(parents=True)
    (prof / "metadata.json").write_text(json.dumps({"email": f"{name}@example.com"}))
    (prof / "cookies.json").write_text(
        json.dumps([{"name": "SID", "value": "x", "domain": ".google.com", "path": "/"}])
    )
    return root, prof


def _seed_no_keystore_probe(root, *answered):
    """Make the real subprocess skip every keystore probe and the startup protect prompt.

    The wizard subprocess has no pytest keystore guard, so an unseeded profile would
    probe the REAL OS keystore. Keys match core/notices.py (protect_answered, probe).
    """
    import json
    import time

    (root / "notices.json").write_text(
        json.dumps(
            {
                "protect_answered": {n: "no" for n in answered},
                "probe": {"result": "unavailable", "checked_at": time.time()},
            }
        )
    )


def test_credential_protection_with_no_saved_logins_says_so(run):
    w = run()
    w.choose(MENU, "Credential protection")
    w.expect("No saved logins yet")
    w.expect(MENU)
    assert w.quit() == 0


def test_credential_protection_door_lists_plain_login_and_back_changes_nothing(run, sandbox):
    root, prof = _seed_plain_login(sandbox)
    _seed_no_keystore_probe(root, "default")
    w = run()
    w.choose(MENU, "Credential protection")
    w.expect("plain")
    w.expect("Protect saved logins")
    w.choose("Credential protection", "Back")
    w.expect(MENU)
    assert w.quit() == 0
    assert (prof / "cookies.json").exists()
