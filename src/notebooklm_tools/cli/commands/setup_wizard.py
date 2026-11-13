"""Interactive setup wizard for adding and removing Gemini Notebook MCP and skills."""

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import questionary
from rich.panel import Panel
from rich.table import Table

from notebooklm_tools.cli.commands import setup, skill
from notebooklm_tools.cli.commands.setup import WIZARD_STYLE, ask_with_back
from notebooklm_tools.cli.setup_safety import ConfigParseError, capture_backups
from notebooklm_tools.cli.utils import make_console

console = make_console()

LEGEND_SELECT = "● = will do it   ○ = skip"
LEGEND_CONNECT = "● = will do it   ○ = skip   ·   nothing is pre-selected"
LEGEND_REMOVE = "● = will remove   ○ = keep"
REASSURANCE_LINE = "Originals backed up in case you want to revert."


@dataclass(frozen=True)
class PickerRow:
    """One row in a grouped questionary picker."""

    group: str | None
    label: str
    value: str
    checked: bool = False
    disabled: str | None = None
    note: str | None = None


def rows_to_choices(rows: list[PickerRow]) -> list:
    """Convert PickerRows into questionary Separators + Choices, grouped.

    A separator is emitted once per non-empty group when the group name changes.
    """
    out: list = []
    last_group: object = object()
    for row in rows:
        if row.group and row.group != last_group:
            out.append(questionary.Separator(f"── {row.group} ──"))
            last_group = row.group
        title = f"{row.label}   {row.note}" if row.note else row.label
        out.append(
            questionary.Choice(
                title=title, value=row.value, checked=row.checked, disabled=row.disabled
            )
        )
    return out


@dataclass(frozen=True)
class SetupTarget:
    """Represents a potential AI tool target for MCP configuration."""

    id: str
    label: str
    installed: bool
    configured: bool
    destination: Path | None
    skill_id: str | None
    repair_reason: str | None = None


@dataclass(frozen=True)
class SetupResult:
    """Represents the outcome of a setup or removal action."""

    id: str
    status: str  # "configured", "already", "repaired", "skipped", "failed", "partial", "removed"
    destination: Path | None
    backup_paths: tuple[Path, ...]
    message: str


class _BackRequested(Exception):
    """Esc pressed inside a nested prompt: abandon the current door, back to the menu."""


def is_interactive() -> bool:
    """Return whether the current session is an interactive TTY."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def copy_to_clipboard(value: str) -> bool:
    """Copy text to the system clipboard using platform utilities."""
    system = platform.system()
    try:
        if system == "Darwin":
            pbcopy = shutil.which("pbcopy")
            if pbcopy:
                res = subprocess.run([pbcopy], input=value.encode("utf-8"), check=False, timeout=5)
                return res.returncode == 0
        elif system == "Windows":
            clip = shutil.which("clip") or "clip.exe"
            res = subprocess.run([clip], input=value.encode("utf-8"), check=False, timeout=5)
            return res.returncode == 0
        else:
            # Linux: try wl-copy, then xclip, then xsel
            for cmd in (
                ["wl-copy"],
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ):
                if shutil.which(cmd[0]):
                    res = subprocess.run(cmd, input=value.encode("utf-8"), check=False, timeout=5)
                    if res.returncode == 0:
                        return True
    except (subprocess.SubprocessError, OSError):
        pass
    return False


def scan_mcp_targets() -> list[SetupTarget]:
    """Scan the system for supported MCP clients, combining Codex/ChatGPT and excluding Alef."""
    targets: list[SetupTarget] = []

    # Combined Codex CLI / ChatGPT desktop target
    codex_dest = setup._codex_config_path() / "config.toml"
    codex_installed = setup._detect_tool("codex")
    codex_configured = setup._is_already_configured("codex")
    codex_repair = setup._codex_repair_reason(codex_dest) if codex_configured else None

    targets.append(
        SetupTarget(
            id="codex",
            label="Codex CLI / ChatGPT desktop app",
            installed=codex_installed,
            configured=codex_configured,
            destination=codex_dest,
            skill_id="agents",
            repair_reason=codex_repair,
        )
    )

    # GitHub Copilot (user profile default for wizard)
    copilot_dest = setup._github_copilot_config_path(scope="user")
    copilot_installed = setup._detect_tool("github-copilot")
    copilot_configured = setup._is_copilot_configured(scope="user")
    targets.append(
        SetupTarget(
            id="github-copilot",
            label="GitHub Copilot (user profile)",
            installed=copilot_installed,
            configured=copilot_configured,
            destination=copilot_dest,
            skill_id=None,
            repair_reason=setup._old_name_reason("github-copilot") if copilot_configured else None,
        )
    )

    # Other tools
    for client_id, info in setup.CLIENT_REGISTRY.items():
        if client_id in ("codex", "github-copilot", "alef-agent"):
            continue

        installed = setup._detect_tool(client_id)
        configured = setup._is_already_configured(client_id) if installed else False

        # Destination path
        dest = None
        if client_id == "claude-desktop":
            paths = setup._claude_desktop_profile_paths()
            dest = next(iter(paths.values())) if paths else setup._claude_desktop_config_path()
        elif client_id == "gemini":
            dest = setup._gemini_config_path()
        elif client_id == "cursor":
            dest = setup._cursor_config_path()
        elif client_id == "windsurf":
            dest = setup._windsurf_config_path()
        elif client_id == "cline":
            dest = setup._cline_config_path()
        elif client_id == "antigravity":
            dest = setup._antigravity_config_path()
        elif client_id == "opencode":
            dest = setup._opencode_config_path()

        skill_id = client_id if client_id in skill.TOOL_CONFIGS else None
        if client_id == "gemini":
            # Gemini CLI shares the "agents" skill file (TOOL_CONFIGS key "gemini-cli").
            skill_id = "gemini-cli"
        if client_id == "claude-desktop":
            # Claude desktop is MCP-only unless claude-code is installed
            skill_id = None

        targets.append(
            SetupTarget(
                id=client_id,
                label=info["name"],
                installed=installed,
                configured=configured,
                destination=dest,
                skill_id=skill_id,
                repair_reason=setup._old_name_reason(client_id) if configured else None,
            )
        )

    return targets


def add_one_mcp(client: str, *, repair: bool = False) -> bool:
    """Configure MCP for one client using its adapter."""
    if client == "github-copilot":
        return setup._setup_github_copilot(scope="user")
    elif client == "codex":
        return setup._setup_codex(repair=repair)
    elif client == "claude-desktop":
        # Ask for the profile here so Esc can be reported as a skip, not a failure.
        profiles = setup._select_claude_desktop_profile_paths()
        if profiles is None:
            raise _BackRequested
        if not profiles:
            return False
        profile = next(iter(profiles)) if len(profiles) == 1 else setup.CLAUDE_DESKTOP_PROFILE_BOTH
        return setup._setup_claude_desktop(profile=profile)
    elif client == "claude-code":
        return setup._setup_claude_code()
    elif client == "gemini":
        return setup._setup_gemini()
    elif client == "cursor":
        return setup._setup_cursor()
    elif client == "windsurf":
        return setup._setup_windsurf()
    elif client == "cline":
        return setup._setup_cline()
    elif client == "antigravity":
        return setup._setup_antigravity()
    elif client == "opencode":
        return setup._setup_opencode()
    return False


def run_add(selected: list[str]) -> list[SetupResult]:
    """Execute Add MCP setup for all selected tools, isolating failures."""
    results: list[SetupResult] = []
    targets = {target.id: target for target in scan_mcp_targets()}

    for client in selected:
        target = targets.get(client)
        dest = target.destination if target else None

        if target and target.configured and target.repair_reason is None:
            results.append(SetupResult(client, "already", dest, (), "Already configured"))
            continue

        configured = False
        recorded: list[Path] = []
        try:
            with capture_backups() as recorded:
                repairing = bool(target and target.repair_reason is not None)
                configured = add_one_mcp(client, repair=repairing)
                if not configured:
                    status, message = "failed", "Setup failed"
                elif repairing and target.repair_reason == setup.OLD_NAME_REASON:
                    status, message = "repaired", f"Renamed to {setup.MCP_SERVER_NAME}"
                elif repairing:
                    status, message = "repaired", "Fixed"
                else:
                    status, message = "configured", "Configured"
        except _BackRequested:
            results.append(SetupResult(client, "skipped", dest, (), "Skipped (Esc)"))
            continue
        except KeyboardInterrupt:
            results.append(
                SetupResult(
                    client, "partial", dest, tuple(recorded), "Interrupted; inspect this target"
                )
            )
            _display_results_summary("Connection Results (partial)", results)
            raise
        except (OSError, ConfigParseError, ValueError) as exc:
            status, message = "failed", str(exc)

        if (
            not configured
            and client == "codex"
            and target
            and not target.configured
            and setup._is_already_configured("codex")
        ):
            status, message = (
                "partial",
                "Codex entry exists, but timeout setup failed; inspect backup",
            )

        results.append(SetupResult(client, status, dest, tuple(recorded), message))

    return results


def _display_results_summary(title: str, results: list[SetupResult]) -> None:
    """Print a Rich table summarizing actions and backup locations."""
    if not results:
        return

    table = Table(title=title, padding=(0, 2))
    table.add_column("Target", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Notes")

    any_backup = False
    for res in results:
        status_style = {
            "configured": "[green]✓ connected[/green]",
            "already": "[green]✓ already connected[/green]",
            "repaired": "[green]✓ repaired[/green]",
            "removed": "[green]✓ removed[/green]",
            "created": "[green]✓ created[/green]",
            "skipped": "[yellow]skipped[/yellow]",
            "failed": "[red]✗ failed[/red]",
            "partial": "[yellow]⚠ partial[/yellow]",
        }.get(res.status, res.status)

        table.add_row(res.id, status_style, res.message)
        any_backup = any_backup or bool(res.backup_paths)

    console.print()
    console.print(table)
    if any_backup:
        console.print(f"\n[dim]{REASSURANCE_LINE}[/dim]")


def build_status_rows(targets: list[SetupTarget], state_fn) -> list[dict]:
    """Assemble per-tool status: connection state + skill state/version/upgrade."""
    rows: list[dict] = []
    for t in targets:
        if t.configured and t.repair_reason == setup.OLD_NAME_REASON:
            conn = "⚠ old name"
        elif t.configured and t.repair_reason:
            conn = "⚠ needs a fix"
        else:
            conn = "✓ set up" if t.configured else "✗ not yet"
        st = state_fn(t)
        if not st["supported"]:
            skill_cell = "– n/a"
        elif not st["installed"]:
            skill_cell = "✗ not yet"
        elif st["upgrade_available"]:
            old = f"v{st['version']}" if st["version"] else "unversioned"
            skill_cell = f"⬆ {old} → v{st['package_version']}"
        else:
            skill_cell = f"✓ v{st['version']}"
        rows.append({"tool": t.label, "connection": conn, "skill": skill_cell})
    return rows


def _skill_state_for(target: SetupTarget) -> dict:
    """Skill version state for a target, keyed by its skill tool id."""
    tool = target.skill_id or target.id
    return skill.skill_version_state(tool, "user")


def _status_markup(cell: str) -> str:
    """Color a status cell by its leading glyph (green=set, red=missing,
    yellow=upgrade, dim=n/a)."""
    if cell.startswith("✓"):
        return f"[green]{cell}[/green]"
    if cell.startswith("✗"):
        return f"[red]{cell}[/red]"
    if cell.startswith(("⬆", "⚠")):
        return f"[yellow]{cell}[/yellow]"
    if cell.startswith("–"):
        return f"[dim]{cell}[/dim]"
    return cell


def _flow_status() -> int:
    """Show a table of detected tools with connection + skill state."""
    detected = [t for t in scan_mcp_targets() if t.installed]
    if not detected:
        console.print("[yellow]No supported AI tools detected on your system.[/yellow]")
        return 0
    rows = build_status_rows(detected, _skill_state_for)
    table = Table(title="Your AI Tools", title_style="italic cyan", padding=(0, 2))
    table.add_column("Tool", style="bold", header_style="bold cyan")
    table.add_column("Connection (MCP)", justify="center", header_style="bold cyan")
    table.add_column("Skill", justify="center", header_style="bold cyan")
    for r in rows:
        table.add_row(r["tool"], _status_markup(r["connection"]), _status_markup(r["skill"]))
    console.print()
    console.print(table)
    console.print("[dim]Only tools found on your machine are shown.[/dim]")
    if any(r["connection"].startswith("⚠") for r in rows):
        console.print('[dim]⚠ = pick "Add the MCP to my tools/agents" to fix it.[/dim]')
    return 0


def _flow_skill_add() -> int:
    """Standalone 'Add the skill' door (scope + skill picker, no MCP step)."""
    return 0 if _flow_skill_offer([], ask_first=False) else 130


def _check_wizard_protect_prompt() -> None:
    """Prompt the user in the wizard to protect credentials if eligible.

    Shares protect_answered with nlm login (asks once, defaults to No).
    """
    if not is_interactive():
        return

    from notebooklm_tools.services.auth import AuthManager
    from notebooklm_tools.services.auth_storage import CredentialStore, set_storage_mode
    from notebooklm_tools.services.notices import (
        get_protect_answer,
        record_protect_answer,
    )
    from notebooklm_tools.utils.config import get_config

    try:
        profile = get_config().auth.default_profile
        if not AuthManager(profile).profile_exists():
            return

        if get_protect_answer(profile) is not None:
            return

        store = CredentialStore()
        if not store.should_offer_protection(profile_name=profile):
            return

        console.print()
        ans = questionary.confirm(
            f"Protect the '{profile}' saved login in your OS keystore?",
            default=False,
            style=WIZARD_STYLE,
        ).ask()

        if ans is None:
            return

        record_protect_answer(profile, "yes" if ans else "no")
        if ans:
            try:
                set_storage_mode(mode="protected", profile_name=profile)
            except Exception as exc:
                console.print(f"[yellow]Could not enable protected mode:[/yellow] {exc}")
                return
            console.print(f"[green]✓[/green] Profile '{profile}' is now protected.")
            if sys.platform == "darwin":
                console.print(
                    "[dim]Usually no popup. If one appears, enter your Mac login password and click Always Allow.[/dim]"
                )
    except Exception:
        pass


def _flow_credential_protection() -> int:
    """Wizard door: protect saved logins, or restore protected ones to plain files."""
    from notebooklm_tools.cli import protection_flow as pf
    from notebooklm_tools.services import auth_storage

    if os.environ.get("NLM_AUTH_STORAGE"):
        console.print(
            "Storage mode is pinned by NLM_AUTH_STORAGE in your environment. "
            "Unset it to change protection here."
        )
        return 0

    modes = pf.profile_modes()
    if not modes:
        console.print("No saved logins yet. Run 'nlm login' first.")
        return 0

    for name, mode in modes.items():
        console.print(f"  {name}   {pf.MODE_LABEL.get(mode, 'unknown')}")
    console.print()

    plain = [n for n, m in modes.items() if m == "file"]
    protected = [n for n, m in modes.items() if m == "protected"]
    protect_label = "Protect saved logins (recommended)"
    restore_label = "Restore protected logins to plain files"
    choices = ([protect_label] if plain else []) + ([restore_label] if protected else [])
    choices.append("Back")

    choice = ask_with_back(
        questionary.select(
            "Credential protection",
            choices=choices,
            instruction="(↑↓ move · Enter select · Esc to go back)",
            style=WIZARD_STYLE,
        )
    )
    if choice is None or choice == "Back":
        return 0

    mode = "protected" if choice == protect_label else "file"
    candidates = plain if mode == "protected" else protected

    if mode == "protected" and not auth_storage.keystore_available():
        console.print(
            "Your OS keystore isn't available right now (locked or not a desktop session). "
            "Nothing changed."
        )
        return 0

    if len(candidates) == 1:
        name = candidates[0]
        question = (
            f"Protect '{name}'?"
            if mode == "protected"
            else f"Restore '{name}' to a plain file? Anyone who can read your files could read the login."
        )
        ok = questionary.confirm(question, default=(mode == "protected"), style=WIZARD_STYLE).ask()
        targets = [name] if ok else []
    else:
        targets = pf.pick_profiles_for_mode(list(modes), mode, modes) or []

    if not targets:
        console.print("[dim]Nothing selected. No changes.[/dim]")
        return 0

    results, errors = pf.apply_mode(mode, targets)
    for res in results:
        console.print(f"[green]✓[/green] {res['message']}")
        auth_storage.record_protect_choice(res["profile"], mode == "protected")
    for err in errors:
        console.print(f"[red]Error:[/red] {err}")
    pf.after_switch(mode, results)
    return 0


def run_setup_wizard() -> int:
    """Run the guided setup wizard. Returns process exit code."""
    if not is_interactive():
        console.print("[yellow]nlm setup requires an interactive terminal.[/yellow]")
        console.print("To configure tools directly, use explicit commands:")
        console.print("  nlm setup add <client>")
        console.print("  nlm setup remove <client>")
        console.print("  nlm setup list")
        console.print("  nlm skill install <tool>")
        return 1

    console.print("[bold cyan]Gemini Notebook Setup Wizard[/bold cyan]")
    console.print("Easily configure Gemini Notebook MCP server and skills for your AI tools.\n")

    _check_wizard_protect_prompt()

    try:
        while True:
            choice = ask_with_back(
                questionary.select(
                    "What would you like to do?",
                    choices=[
                        "Show my tools' status",
                        "Add the MCP to my tools/agents",
                        "Add the skill to my tools/agents",
                        "Remove an MCP or skill",
                        "Credential protection",
                        "Copy MCP setup for a tool not listed",
                        "Exit",
                    ],
                    instruction="(↑↓ move · Enter select · Esc to quit)",
                    style=WIZARD_STYLE,
                )
            )

            if choice is None:
                return 130
            if choice == "Exit":
                return 0

            if choice.startswith("Show"):
                _flow_status()
            elif choice.startswith("Add the MCP"):
                _flow_add()
            elif choice.startswith("Add the skill"):
                _flow_skill_add()
            elif choice.startswith("Remove"):
                _flow_remove()
            elif choice.startswith("Credential"):
                _flow_credential_protection()
            elif choice.startswith("Copy"):
                _flow_json()

            # A door finished (or the user pressed Esc inside it): return to the
            # main menu instead of quitting the wizard.
            console.print()
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup cancelled by user.[/yellow]")
        return 130


def build_connect_rows(detected: list[SetupTarget]) -> list[PickerRow]:
    """Group detected tools for the connect picker; no paths, plain repair note."""
    needs_fix: list[PickerRow] = []
    not_yet: list[PickerRow] = []
    already: list[PickerRow] = []
    for t in detected:
        if t.repair_reason:
            note = (
                "⚠ uses the old name"
                if t.repair_reason == setup.OLD_NAME_REASON
                else "⚠ quick fix needed"
            )
            needs_fix.append(PickerRow("Needs a fix", t.label, t.id, note=note))
        elif not t.configured:
            not_yet.append(PickerRow("Not connected yet", t.label, t.id))
        else:
            already.append(
                PickerRow("Already connected", t.label, t.id, disabled="already connected")
            )
    return needs_fix + not_yet + already


def _flow_add() -> int:
    """Interactive Add MCP flow."""
    console.print("\n[bold]Scanning for installed AI tools...[/bold]\n")
    targets = scan_mcp_targets()
    detected = [t for t in targets if t.installed]

    if not detected:
        console.print("[yellow]No supported MCP clients detected on your system.[/yellow]")
        console.print("You can still install the skill for a detected skill-capable tool.")
        return 0 if _flow_skill_offer([]) else 130

    console.print(f"[dim]{LEGEND_CONNECT}[/dim]")
    selected = ask_with_back(
        questionary.checkbox(
            "Select which tools to connect:",
            choices=rows_to_choices(build_connect_rows(detected)),
            instruction="(↑↓ move · Space toggle · A all · Enter confirm · Esc to go back)",
            style=WIZARD_STYLE,
        )
    )

    if selected is None:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130

    if not selected:
        console.print("[dim]No tools selected.[/dim]")
        return 0 if _flow_skill_offer([]) else 130

    results = run_add(selected)
    _display_results_summary("Connection Results", results)

    # Only claim success in the skill offer if at least one connection landed.
    connected_ok = any(r.status in {"configured", "already", "repaired"} for r in results)

    # Offer optional skill
    return 0 if _flow_skill_offer(selected, post_connect=True, connected_ok=connected_ok) else 130


def build_skill_rows(tool_options, level: str, selected_mcp_ids: list[str]) -> list[PickerRow]:
    """Rows for the skill picker: no paths, shared-file note, version/upgrade flags."""
    rows: list[PickerRow] = []
    seen: set[Path] = set()
    for tool_key, label, mcp_keys in tool_options:
        dest = skill.get_skill_destination(tool_key, level)
        if not dest or dest in seen:
            continue
        installed = any(setup._detect_tool(k) for k in mcp_keys) or skill._is_tool_installed(
            tool_key
        )
        if not installed:
            continue
        seen.add(dest)
        state = skill.skill_version_state(tool_key, level)
        row_label = f"{label}   · one shared file covers these" if tool_key == "agents" else label
        if state["upgrade_available"]:
            note = "· upgrade available"
        elif state["installed"] and state["version"]:
            note = f"· v{state['version']} installed"
        else:
            note = None
        checked = any(k in selected_mcp_ids for k in mcp_keys) or state["upgrade_available"]
        rows.append(PickerRow(None, row_label, tool_key, checked=checked, note=note))
    return rows


UPLOAD_ROW_VALUE = "claude-desktop-upload"


def with_upload_row(rows: list[PickerRow]) -> list[PickerRow]:
    """Append the always-offered, never pre-ticked Claude Desktop / claude.ai row."""
    return [
        *rows,
        PickerRow(
            None, "Claude Desktop / claude.ai", UPLOAD_ROW_VALUE, note="· creates a file to upload"
        ),
    ]


def _make_upload_zip() -> SetupResult:
    from notebooklm_tools.cli import skill_package as sp

    try:
        zip_path = sp.build_skill_zip(sp.default_output_dir())
    except (OSError, ValueError) as exc:
        return SetupResult(UPLOAD_ROW_VALUE, "failed", None, (), f"Couldn't create file: {exc}")
    return SetupResult(UPLOAD_ROW_VALUE, "created", zip_path, (), "File ready to upload")


def _show_upload_steps(zip_path: Path) -> None:
    """Last thing on screen: where the file is and how to upload it."""
    from notebooklm_tools.cli import skill_package as sp

    console.print()
    console.print(
        Panel(
            "\n".join(sp.upload_instructions(zip_path)),
            title="Claude Desktop / claude.ai",
            border_style="cyan",
        )
    )
    sp.reveal_in_file_manager(zip_path)


def _flow_skill_offer(
    selected_mcp_ids: list[str],
    post_connect: bool = False,
    connected_ok: bool = True,
    ask_first: bool = True,
) -> bool:
    """Skill installation: an optional offer after connecting (ask_first), or the
    standalone "Add the skill" door, which goes straight to the choices."""
    console.print("\n[bold]Gemini Notebook skill[/bold]")
    console.print("Teaches your AI tools how to use Gemini Notebook well.\n")

    if ask_first:
        if post_connect and connected_ok:
            prompt = "Connection added. Also add the skill? (recommended)"
        elif post_connect:
            # The connection failed; don't claim it succeeded.
            prompt = "The connection didn't complete. Add the skill anyway?"
        else:
            prompt = "Add the skill? (recommended)"
        want_skill = ask_with_back(questionary.confirm(prompt, default=True, style=WIZARD_STYLE))
        if want_skill is None:
            return False
        if not want_skill:
            return True

    level_choice = ask_with_back(
        questionary.select(
            "Where should the skill live?",
            choices=[
                "All my projects      (recommended)",
                "Just this folder",
            ],
            instruction="(↑↓ move · Enter select · Esc to go back)",
            style=WIZARD_STYLE,
        )
    )

    if level_choice is None:
        return False

    level = "user" if "projects" in level_choice else "project"

    # Determine eligible tools
    # Deduplicate shared targets: codex, chatgpt-desktop, gemini-cli all share "agents"
    tool_options = [
        ("agents", "Agents / Codex / ChatGPT / Gemini CLI", ["codex", "gemini"]),
        ("claude-code", "Claude Code CLI", ["claude-code"]),
        ("cursor", "Cursor AI editor", ["cursor"]),
        ("opencode", "OpenCode assistant", ["opencode"]),
        ("antigravity", "Antigravity framework", ["antigravity"]),
        ("cline", "Cline CLI", ["cline"]),
        ("hermes", "Hermes Agent", ["hermes"]),
        ("openclaw", "OpenClaw framework", ["openclaw"]),
    ]

    skill_rows = with_upload_row(build_skill_rows(tool_options, level, selected_mcp_ids))

    console.print(f"[dim]{LEGEND_SELECT}[/dim]")
    chosen_skills = ask_with_back(
        questionary.checkbox(
            "Add the skill to which tools?",
            choices=rows_to_choices(skill_rows),
            instruction="(↑↓ move · Space toggle · A all · Enter confirm · Esc to go back)",
            style=WIZARD_STYLE,
        )
    )
    if chosen_skills is None:
        return False
    if not chosen_skills:
        return True

    # The upload file isn't a local install: make it after the local tools, so a
    # failure there can't block them.
    make_upload = UPLOAD_ROW_VALUE in chosen_skills
    chosen_skills = [sk for sk in chosen_skills if sk != UPLOAD_ROW_VALUE]

    skill_results = []
    for sk in chosen_skills:
        recorded: list[Path] = []
        try:
            with capture_backups() as recorded:
                outcome = skill.skill_action(
                    sk, level, "install", confirm_replace=_confirm_skill_replace
                )
        except _BackRequested:
            # Esc at the replace question: nothing was changed for this skill yet.
            _display_results_summary("Skill Setup Results", skill_results)
            console.print("\n[yellow]Cancelled.[/yellow]")
            return False
        except KeyboardInterrupt:
            skill_results.append(
                SetupResult(
                    sk,
                    "partial",
                    skill.get_skill_destination(sk, level),
                    tuple(recorded),
                    "Interrupted; inspect this skill",
                )
            )
            _display_results_summary("Skill Setup Results (partial)", skill_results)
            raise
        backups = (outcome.backup_path,) if outcome.backup_path else ()
        skill_results.append(
            SetupResult(sk, outcome.status, outcome.path, backups, outcome.message)
        )

    upload = _make_upload_zip() if make_upload else None
    if upload:
        skill_results.append(upload)
    _display_results_summary("Skill Setup Results", skill_results)
    if upload and upload.status == "created":
        _show_upload_steps(upload.destination)
    return True


def _confirm_skill_replace(message: str) -> bool:
    """Require an explicit yes before replacing an installed skill."""
    answer = ask_with_back(questionary.confirm(message, default=False, style=WIZARD_STYLE))
    if answer is None:
        raise _BackRequested
    return answer


def _flow_json() -> int:
    """Generate generic JSON snippet with clipboard support."""
    setup._setup_json()
    return 0


def scan_removable() -> list[SetupTarget]:
    """Scan the system for removable Gemini Notebook MCP entries and skills."""
    targets: list[SetupTarget] = []

    # 1. Claude Desktop profiles
    try:
        profiles = setup._claude_desktop_profile_paths()
        for p_name, p_path in profiles.items():
            if p_path.exists():
                try:
                    cfg = setup._read_json_config(p_path)
                    if setup._is_configured(cfg):
                        targets.append(
                            SetupTarget(
                                id=f"claude-desktop:{p_name}",
                                label=f"Claude Desktop ({p_name})",
                                installed=True,
                                configured=True,
                                destination=p_path,
                                skill_id=None,
                            )
                        )
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Claude Code
    try:
        if setup._is_already_configured("claude-code"):
            targets.append(
                SetupTarget(
                    id="claude-code",
                    label="Claude Code",
                    installed=True,
                    configured=True,
                    destination=Path.home() / ".claude.json",
                    skill_id="claude-code",
                )
            )
    except Exception:
        pass

    # 3. Codex CLI / ChatGPT desktop
    try:
        if setup._is_already_configured("codex"):
            targets.append(
                SetupTarget(
                    id="codex",
                    label="Codex CLI / ChatGPT desktop",
                    installed=True,
                    configured=True,
                    destination=setup._codex_config_path() / "config.toml",
                    skill_id="codex",
                )
            )
    except Exception:
        pass

    # 4. GitHub Copilot (user and project scopes)
    for scope in ("user", "project"):
        try:
            if setup._is_copilot_configured(scope=scope):
                dest = setup._github_copilot_config_path(scope=scope)
                scope_label = "user profile" if scope == "user" else "project"
                targets.append(
                    SetupTarget(
                        id=f"github-copilot:{scope}",
                        label=f"GitHub Copilot ({scope_label})",
                        installed=True,
                        configured=True,
                        destination=dest,
                        skill_id=None,
                    )
                )
        except Exception:
            pass

    # 5. Standard JSON clients (excluding alef-agent)
    standard_clients = [
        ("cursor", "Cursor", setup._cursor_config_path),
        ("windsurf", "Windsurf", setup._windsurf_config_path),
        ("cline", "Cline", setup._cline_config_path),
        ("antigravity", "Antigravity", setup._antigravity_config_path),
        ("gemini", "Gemini CLI", setup._gemini_config_path),
        ("opencode", "OpenCode", setup._opencode_config_path),
    ]
    for cid, label, path_fn in standard_clients:
        try:
            if setup._is_already_configured(cid):
                targets.append(
                    SetupTarget(
                        id=cid,
                        label=label,
                        installed=True,
                        configured=True,
                        destination=path_fn(),
                        skill_id=cid,
                    )
                )
        except Exception:
            pass

    # 6. Skills (user and project scopes; exclude alef-agent)
    skill_tools = [
        "agents",
        *(tool for tool in skill.TOOL_CONFIGS if tool not in {"agents", "alef-agent", "other"}),
    ]
    seen_destinations: set[Path] = set()
    for tool_name in skill_tools:
        for level in ("user", "project"):
            try:
                installed, path = skill.check_install_status(tool_name, level)
                if installed and path and path not in seen_destinations:
                    seen_destinations.add(path)
                    label = (
                        "nlm-skill (shared: Codex, ChatGPT, Gemini, Antigravity)"
                        if tool_name == "agents"
                        else f"nlm-skill ({tool_name.replace('-', ' ').title()})"
                    )
                    targets.append(
                        SetupTarget(
                            id=f"skill:{tool_name}:{level}",
                            label=f"{label} [{level}]",
                            installed=True,
                            configured=True,
                            destination=path,
                            skill_id=tool_name,
                        )
                    )
            except Exception:
                pass

    return targets


def remove_mcp_targets(
    targets: list[SetupTarget], on_result: Callable[[SetupResult], None] | None = None
) -> list[SetupResult]:
    """Safely remove selected MCP targets with backups and error isolation."""
    results = []
    for target in targets:
        client, _, profile = target.id.partition(":")
        recorded: list[Path] = []
        try:
            with capture_backups() as recorded:
                scope = (
                    profile
                    if profile in ("user", "project")
                    else ("user" if client == "github-copilot" else "project")
                )
                prof = profile if profile not in ("user", "project") else None
                removed = setup._remove_single(
                    client,
                    profile=prof,
                    scope=scope,
                )
                status, message = (
                    ("removed", "Removed") if removed else ("failed", "Removal failed")
                )
        except KeyboardInterrupt:
            partial = SetupResult(
                target.id,
                "partial",
                target.destination,
                tuple(recorded),
                "Interrupted; inspect this target",
            )
            results.append(partial)
            if on_result:
                on_result(partial)
            raise
        except (OSError, ConfigParseError, ValueError) as exc:
            status, message = "failed", str(exc)
        result = SetupResult(target.id, status, target.destination, tuple(recorded), message)
        results.append(result)
        if on_result:
            on_result(result)
    return results


def remove_skill_targets(
    targets: list[SetupTarget], on_result: Callable[[SetupResult], None] | None = None
) -> list[SetupResult]:
    """Safely remove selected skill targets with directory backups."""
    results = []
    for target in targets:
        _, tool, level = target.id.split(":", 2)
        try:
            outcome = skill.skill_action(tool, level, "remove", confirm_replace=lambda _: True)
        except KeyboardInterrupt:
            partial = SetupResult(
                target.id, "partial", target.destination, (), "Interrupted; inspect this skill"
            )
            results.append(partial)
            if on_result:
                on_result(partial)
            raise
        backups = (outcome.backup_path,) if outcome.backup_path else ()
        result = SetupResult(
            target.id, outcome.status, target.destination, backups, outcome.message
        )
        results.append(result)
        if on_result:
            on_result(result)
    return results


def skipped(targets: list[SetupTarget]) -> list[SetupResult]:
    """Return skipped results for cancelled targets."""
    return [SetupResult(t.id, "skipped", t.destination, (), "Cancelled") for t in targets]


def run_remove(selected: list[str]) -> list[SetupResult]:
    """Run removal on selected target IDs with two-stage confirmation."""
    all_removable = {t.id: t for t in scan_removable()}
    mcp_targets = [
        all_removable[i] for i in selected if i in all_removable and not i.startswith("skill:")
    ]
    skill_targets = [
        all_removable[i] for i in selected if i in all_removable and i.startswith("skill:")
    ]
    results = []
    try:
        if mcp_targets:
            allowed = ask_with_back(
                questionary.confirm(
                    "Remove the selected MCP entries?", default=False, style=WIZARD_STYLE
                )
            )
            if allowed is None:
                raise KeyboardInterrupt
            if allowed:
                remove_mcp_targets(mcp_targets, on_result=results.append)
            else:
                results.extend(skipped(mcp_targets))
        if skill_targets:
            allowed = ask_with_back(
                questionary.confirm(
                    "Delete the listed skill folders? Personal edits in the active folders will be removed.",
                    default=False,
                    style=WIZARD_STYLE,
                )
            )
            if allowed is None:
                raise KeyboardInterrupt
            if allowed:
                remove_skill_targets(skill_targets, on_result=results.append)
            else:
                results.extend(skipped(skill_targets))
    except KeyboardInterrupt:
        _display_results_summary("Removal Results (partial)", results)
        raise
    return results


def build_remove_rows(targets: list[SetupTarget]) -> list[PickerRow]:
    """Group removable targets into MCP connections and Skills; opt-in, short paths."""
    mcp_rows: list[PickerRow] = []
    skill_rows: list[PickerRow] = []
    for t in targets:
        note = str(t.destination).replace(str(Path.home()), "~") if t.destination else None
        if t.id.startswith("skill:"):
            skill_rows.append(PickerRow("Skills", t.label, t.id, note=note))
        else:
            mcp_rows.append(PickerRow("MCP connections", t.label, t.id, note=note))
    return mcp_rows + skill_rows


def _flow_remove() -> int:
    """Interactively select and remove MCP configurations and skills."""
    targets = scan_removable()
    if not targets:
        console.print("[dim]No Gemini Notebook MCP entries or skills found to remove.[/dim]")
        return 0

    try:
        console.print(f"[dim]{LEGEND_REMOVE}[/dim]")
        selected_labels = ask_with_back(
            questionary.checkbox(
                "Select what to remove:",
                choices=rows_to_choices(build_remove_rows(targets)),
                instruction="(↑↓ move · Space toggle · Enter confirm · Esc to go back)",
                style=WIZARD_STYLE,
            )
        )

        if selected_labels is None:
            return 130
        if not selected_labels:
            console.print("[dim]No items selected for removal.[/dim]")
            return 0

        known_ids = {target.id for target in targets}
        selected_ids = [target_id for target_id in selected_labels if target_id in known_ids]

        results = run_remove(selected_ids)
        _display_results_summary("Removal Results", results)
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Removal cancelled by user.[/yellow]")
        return 130
