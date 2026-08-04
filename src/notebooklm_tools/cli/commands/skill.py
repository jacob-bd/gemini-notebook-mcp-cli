"""Skill installer commands for NotebookLM CLI."""

import os
import re
import shutil
from pathlib import Path
from typing import Any, TypedDict

import typer
from rich.table import Table

from notebooklm_tools import __version__
from notebooklm_tools.cli.utils import is_tool_on_system, make_console

console = make_console()
app = typer.Typer(
    name="skill",
    help="Install NotebookLM skills for AI tools",
    no_args_is_help=True,
)

_HOME = Path.home()

# Shared paths: agents, gemini-cli, codex, and antigravity (project) all install here
_AGENTS_USER = _HOME / ".agents" / "skills" / "nlm-skill"
_AGENTS_PROJECT = Path(".agents/skills/nlm-skill")

# Hermes supports $HERMES_HOME override; fall back to ~/.hermes
_HERMES_HOME = Path(os.environ.get("HERMES_HOME") or _HOME / ".hermes")


class ToolConfig(TypedDict, total=False):
    user: Path
    project: Path
    format: str
    description: str
    binary: str
    root_dirs: list[Path]
    frontmatter_extras: dict[str, str]


TOOL_CONFIGS: dict[str, ToolConfig] = {
    "claude-code": {
        "user": _HOME / ".claude" / "skills" / "nlm-skill",
        "project": Path(".claude/skills/nlm-skill"),
        "format": "skill.md",
        "description": "Claude Code CLI and Desktop",
        "binary": "claude",
        "root_dirs": [_HOME / ".claude"],
    },
    "cursor": {
        "user": _HOME / ".cursor" / "skills" / "nlm-skill",
        "project": Path(".cursor/skills/nlm-skill"),
        "format": "skill.md",
        "description": "Cursor AI editor",
        "binary": "cursor",
        "root_dirs": [_HOME / ".cursor"],
    },
    "agents": {
        "user": _AGENTS_USER,
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "Generic agent skill (Gemini CLI, Codex, and others)",
        "root_dirs": [_HOME / ".agents"],
    },
    "gemini-cli": {
        "user": _AGENTS_USER,
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "Google Gemini CLI",
        "binary": "gemini",
        "root_dirs": [_HOME / ".agents", _HOME / ".gemini"],
    },
    "codex": {
        "user": _AGENTS_USER,
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "OpenAI Codex CLI",
        "binary": "codex",
        "root_dirs": [_HOME / ".codex", _HOME / ".agents"],
    },
    "opencode": {
        "user": _HOME / ".config" / "opencode" / "skills" / "nlm-skill",
        "project": Path(".opencode/skills/nlm-skill"),
        "format": "skill.md",
        "description": "OpenCode AI assistant",
        "binary": "opencode",
        "root_dirs": [_HOME / ".config" / "opencode"],
    },
    "antigravity": {
        "user": _HOME / ".gemini" / "antigravity" / "skills" / "nlm-skill",
        "project": _AGENTS_PROJECT,
        "format": "skill.md",
        "description": "Antigravity agent framework",
        "root_dirs": [_HOME / ".gemini" / "antigravity"],
    },
    "cline": {
        "user": _HOME / ".cline" / "skills" / "nlm-skill",
        "project": Path(".cline/skills/nlm-skill"),
        "format": "skill.md",
        "description": "Cline CLI terminal agent",
        "binary": "cline",
        "root_dirs": [_HOME / ".cline"],
    },
    "openclaw": {
        "user": _HOME / ".openclaw" / "workspace" / "skills" / "nlm-skill",
        "project": Path(".openclaw/workspace/skills/nlm-skill"),
        "format": "skill.md",
        "description": "OpenClaw AI agent framework",
        "binary": "openclaw",
        "root_dirs": [_HOME / ".openclaw"],
    },
    "alef-agent": {
        "user": _HOME / ".alef-agent" / "workspace" / "skills" / "nlm-skill",
        "project": Path(".alef-agent/workspace/skills/nlm-skill"),
        "format": "skill.md",
        "description": "Alef Agent AI agent framework",
        "frontmatter_extras": {"type": "tool", "status": "approved"},
        "root_dirs": [_HOME / ".alef-agent"],
    },
    "hermes": {
        "user": _HERMES_HOME / "skills" / "nlm-skill",
        "project": Path(".hermes/skills/nlm-skill"),
        "format": "skill.md",
        "description": "Hermes Agent (NousResearch)",
        "binary": "hermes",
        "root_dirs": [_HERMES_HOME],
    },
    "other": {
        "project": Path("./nlm-skill-export"),
        "format": "all",
        "description": "Export all formats for manual installation",
    },
}


def _is_tool_installed(tool: str) -> bool:
    """Detect whether a tool is actually installed on this system."""
    config = TOOL_CONFIGS.get(tool, {})
    return is_tool_on_system(config.get("binary"), config.get("root_dirs"))


def complete_tool_name(ctx: Any, param: Any, incomplete: str) -> list[str]:
    """Shell completion callback for tool names."""
    return [name for name in TOOL_CONFIGS if name.startswith(incomplete)]


def get_data_dir() -> Path:
    """Get the package data directory containing skill files."""
    import notebooklm_tools

    package_dir = Path(notebooklm_tools.__file__).parent
    data_dir = package_dir / "data"

    if not data_dir.exists():
        console.print(f"[red]Error:[/red] Data directory not found: {data_dir}")
        raise typer.Exit(1)

    return data_dir


def check_install_status(tool: str, level: str = "user") -> tuple[bool, Path | None]:
    """Check if skill is installed for a tool.

    Returns:
        (is_installed, install_path)
    """
    if tool not in TOOL_CONFIGS:
        return False, None

    config = TOOL_CONFIGS[tool]

    # Get install path
    if level == "user" and "user" in config:
        install_path = config["user"]
    elif level == "project" and "project" in config:
        install_path = config["project"]
    else:
        return False, None

    # Check format
    if config["format"] == "skill.md":
        # Check for SKILL.md in directory
        skill_file = install_path / "SKILL.md"
        return skill_file.exists(), install_path
    elif config["format"] == "agents.md":
        # Check for markers in AGENTS.md
        if not install_path.exists():
            return False, install_path
        content = install_path.read_text(encoding="utf-8")
        return "<!-- nlm-skill-start -->" in content, install_path
    elif config["format"] == "all":
        # Check if export directory exists
        return install_path.exists(), install_path

    return False, None


def _inject_version_to_frontmatter(skill_path: Path) -> None:
    """Inject the current package version into the SKILL.md YAML frontmatter."""
    content = skill_path.read_text(encoding="utf-8")
    if content.startswith("---"):
        # Find the closing --- of frontmatter
        end_idx = content.index("---", 3)
        frontmatter = content[3:end_idx]
        # Remove any existing version line
        frontmatter = re.sub(r"\nversion:.*", "", frontmatter)
        # Add version before closing ---
        frontmatter = frontmatter.rstrip() + f'\nversion: "{__version__}"\n'
        content = "---" + frontmatter + "---" + content[end_idx + 3 :]
    else:
        # No frontmatter — prepend one with version
        content = f'---\nversion: "{__version__}"\n---\n\n' + content
    skill_path.write_text(content, encoding="utf-8")


def _inject_frontmatter_extras(skill_path: Path, extras: dict[str, str]) -> None:
    """Inject extra frontmatter fields into SKILL.md for tool-specific compatibility.

    Used to add fields like `type: tool` and `status: approved` for Alef Agent.
    """
    content = skill_path.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return

    end_idx = content.index("---", 3)
    frontmatter = content[3:end_idx]

    for key, value in extras.items():
        # Remove any existing line for this key
        frontmatter = re.sub(rf"\n{re.escape(key)}:.*", "", frontmatter)
        # Add the field
        frontmatter = frontmatter.rstrip() + f"\n{key}: {value}\n"

    content = "---" + frontmatter + "---" + content[end_idx + 3 :]
    skill_path.write_text(content, encoding="utf-8")


def _get_installed_version(tool: str, level: str) -> str | None:
    """Read the version from an installed skill. Returns None if not found."""
    config = TOOL_CONFIGS[tool]
    install_path = config.get(level)
    if not install_path:
        return None

    format_type = config["format"]

    if format_type == "agents.md":
        if not install_path.exists():
            return None
        try:
            content = install_path.read_text(encoding="utf-8")
            match = re.search(r"<!-- nlm-version: ([\d.]+) -->", content)
            return match.group(1) if match else None
        except Exception:
            return None
    elif format_type == "skill.md":
        skill_file = install_path / "SKILL.md"
    elif format_type == "all":
        skill_file = install_path / "nlm-skill" / "SKILL.md"
    else:
        return None

    if not skill_file.exists():
        return None

    try:
        content = skill_file.read_text(encoding="utf-8")
        match = re.search(r'version:\s*"([^"]*)"', content)
        return match.group(1) if match else None
    except Exception:
        return None


def _inject_version_to_agents_md(agents_path: Path) -> None:
    """Inject a version comment into the NLM section of AGENTS.md."""
    try:
        content = agents_path.read_text(encoding="utf-8")
        version_comment = f"<!-- nlm-version: {__version__} -->"

        # Remove any existing version comment
        content = re.sub(r"<!-- nlm-version: [\d.]+ -->\n?", "", content)

        # Insert version comment right after the start marker
        start_marker = "<!-- nlm-skill-start -->"
        if start_marker in content:
            content = content.replace(
                start_marker,
                f"{start_marker}\n{version_comment}",
            )
            agents_path.write_text(content, encoding="utf-8")
    except Exception:
        pass


def install_skill_md(install_path: Path, frontmatter_extras: dict[str, str] | None = None) -> None:
    """Install SKILL.md format to a directory.

    Args:
        install_path: Target directory for the skill files.
        frontmatter_extras: Optional extra frontmatter fields to inject (e.g. for Alef Agent).
    """
    data_dir = get_data_dir()

    # Create directory
    install_path.mkdir(parents=True, exist_ok=True)

    # Copy SKILL.md
    skill_src = data_dir / "SKILL.md"
    skill_dst = install_path / "SKILL.md"
    shutil.copy2(skill_src, skill_dst)

    # Inject current version into frontmatter
    _inject_version_to_frontmatter(skill_dst)

    # Inject tool-specific frontmatter fields (e.g. type/status for Alef Agent)
    if frontmatter_extras:
        _inject_frontmatter_extras(skill_dst, frontmatter_extras)

    # Copy references directory
    ref_src = data_dir / "references"
    ref_dst = install_path / "references"
    if ref_dst.exists():
        shutil.rmtree(ref_dst)
    shutil.copytree(ref_src, ref_dst)

    console.print(f"[green]✓[/green] Installed SKILL.md (v{__version__}) to {install_path}")
    console.print("  [dim]• SKILL.md")
    console.print("  [dim]• references/studio-prompting-guide.md")
    console.print("  [dim]• references/studio-prompt-examples.md")
    console.print("  [dim]• references/command_reference.md")
    console.print("  [dim]• references/troubleshooting.md")
    console.print("  [dim]• references/workflows.md")
    console.print("  [dim]• references/remote-mcp.md")


def install_agents_md(install_path: Path) -> None:
    """Install/update AGENTS.md format (append with markers)."""
    data_dir = get_data_dir()
    section_src = data_dir / "AGENTS_SECTION.md"
    section_content = section_src.read_text(encoding="utf-8")

    # Read existing AGENTS.md or create new
    if install_path.exists():
        content = install_path.read_text(encoding="utf-8")

        # Check if already installed
        if "<!-- nlm-skill-start -->" in content:
            # Update existing section
            start_marker = "<!-- nlm-skill-start -->"
            end_marker = "<!-- nlm-skill-end -->"

            start_idx = content.find(start_marker)
            end_idx = content.find(end_marker)

            if start_idx != -1 and end_idx != -1:
                # Replace existing section
                before = content[:start_idx]
                after = content[end_idx + len(end_marker) :]
                content = before + section_content + after
            else:
                # Malformed markers, append anyway
                content = content.rstrip() + "\n\n" + section_content + "\n"
        else:
            # Append new section
            content = content.rstrip() + "\n\n" + section_content + "\n"
    else:
        # Create new file with section
        install_path.parent.mkdir(parents=True, exist_ok=True)
        content = section_content + "\n"

    install_path.write_text(content, encoding="utf-8")

    # Inject version marker into the NLM section
    _inject_version_to_agents_md(install_path)

    console.print(f"[green]✓[/green] Updated AGENTS.md at {install_path}")
    console.print("  [dim]• NLM section appended with markers")


def install_all_formats(install_path: Path) -> None:
    """Export all skill formats to a directory."""
    data_dir = get_data_dir()

    # Remove existing directory
    if install_path.exists():
        shutil.rmtree(install_path)

    # Create export directory
    install_path.mkdir(parents=True, exist_ok=True)

    # Copy SKILL.md format (with references) - using "nlm-skill" as folder name
    skill_dir = install_path / "nlm-skill"
    skill_dir.mkdir()
    shutil.copy2(data_dir / "SKILL.md", skill_dir / "SKILL.md")
    shutil.copytree(data_dir / "references", skill_dir / "references")

    # Copy AGENTS.md section
    agents_file = install_path / "AGENTS_SECTION.md"
    shutil.copy2(data_dir / "AGENTS_SECTION.md", agents_file)

    # Create README
    readme_content = """# NotebookLM Skill Export

This directory contains NotebookLM skill files in multiple formats.

## Formats Available

### nlm-skill/
- `SKILL.md` - Main skill file for Claude Code, OpenCode, Gemini CLI, Antigravity, Codex
- `references/` - Additional reference documentation

This is the standard skill directory structure used by all automated installations.

### AGENTS_SECTION.md
- Section format for AGENTS.md (copy/paste into your AGENTS.md)

## Installation

### Claude Code
```bash
cp -r nlm-skill ~/.claude/skills/
```

### OpenCode
```bash
cp -r nlm-skill ~/.config/opencode/skills/
```

### Gemini CLI / Codex / Agents (cross-tool compatible)
```bash
cp -r nlm-skill ~/.agents/skills/
```

### Antigravity
```bash
cp -r nlm-skill ~/.gemini/antigravity/skills/
```

### Hermes Agent
```bash
cp -r nlm-skill ~/.hermes/skills/
```

Or for project-level installation, copy to:
- Claude Code: `.claude/skills/`
- OpenCode: `.opencode/skills/`
- Gemini CLI / Codex: `.agents/skills/`
- Antigravity: `.agents/skills/`
- Hermes: `.hermes/skills/`

## Automated Installation

Instead of manual copying, you can use:
```bash
nlm skill install <tool>
```

Where `<tool>` is: claude-code, cursor, agents, opencode, antigravity, hermes, cline, openclaw, alef-agent.

> **Note:** `agents` replaces the old `gemini-cli` and `codex` entries. The `.agents/skills/`
> path is the cross-tool compatible alias supported by Gemini CLI (v0.33.1+), Codex, and others.
"""

    (install_path / "README.md").write_text(readme_content, encoding="utf-8")

    console.print(f"[green]✓[/green] Exported all formats to {install_path}")
    console.print(
        "  [dim]• nlm-skill/ (skill directory for Claude Code, OpenCode, Agents, Antigravity)"
    )
    console.print("  [dim]• AGENTS_SECTION.md (for Codex)")
    console.print("  [dim]• README.md (installation instructions)")


@app.command("install")
def install(
    tool: str = typer.Argument(
        ...,
        help="Tool to install skill for (claude-code, cursor, agents, hermes, opencode, antigravity, other)",
        shell_complete=complete_tool_name,
    ),
    level: str = typer.Option(
        "user",
        "--level",
        "-l",
        help="Install at user level (~/.config) or project level (./)",
    ),
) -> None:
    """
    Install NotebookLM skill for an AI tool.

    Examples:
        nlm skill install claude-code
        nlm skill install agents --level project
        nlm skill install other  # Export all formats
    """
    if level not in ("user", "project"):
        console.print(f"[red]Error:[/red] Invalid level '{level}'. Must be 'user' or 'project'.")
        raise typer.Exit(1)

    if tool not in TOOL_CONFIGS:
        valid_tools = ", ".join(TOOL_CONFIGS.keys())
        console.print(f"[red]Error:[/red] Unknown tool '{tool}'")
        console.print(f"Valid tools: {valid_tools}")
        raise typer.Exit(1)

    config = TOOL_CONFIGS[tool]

    # Check level support
    if level == "user" and "user" not in config:
        if tool == "other":
            # Auto-switch to project level for export
            level = "project"
            console.print("[dim]Note: 'other' exports to current directory (project level)[/dim]")
        else:
            console.print(
                f"[red]Error:[/red] Tool '{tool}' does not support user-level installation"
            )
            console.print("Use --level project instead")
            raise typer.Exit(1)

    # Get install path
    install_path = config.get(level)
    if not install_path:
        install_path = config.get("project")  # Fallback

    # Validate that the tool is installed for user-level installs
    if level == "user" and install_path:
        tool_detected = _is_tool_installed(tool)

        if not tool_detected:
            console.print(
                f"[yellow]Warning:[/yellow] {tool} does not appear to be installed on your system. "
                "No files were changed."
            )
            console.print(
                f"[dim]Install {tool} first, or explicitly use --level project "
                "for a project-local skill.[/dim]"
            )
            raise typer.Exit(0)

    # Check if already installed
    is_installed, _ = check_install_status(tool, level)
    if is_installed:
        console.print(f"[yellow]![/yellow] Skill already installed for {tool} at {level} level")
        if not typer.confirm("Overwrite existing installation?"):
            console.print("Cancelled.")
            raise typer.Exit(0)

    # Install based on format
    format_type = config["format"]

    try:
        if format_type == "skill.md":
            install_skill_md(install_path, config.get("frontmatter_extras"))
        elif format_type == "agents.md":
            install_agents_md(install_path)
        elif format_type == "all":
            install_all_formats(install_path)

        console.print(f"\n[green]✓[/green] Successfully installed skill for [cyan]{tool}[/cyan]")
        console.print(f"  Level: {level}")
        console.print(f"  Path: {install_path}")

    except Exception as e:
        console.print(f"\n[red]✗ Installation failed:[/red] {e}")
        raise typer.Exit(1) from e


@app.command("uninstall")
def uninstall(
    tool: str = typer.Argument(
        ...,
        help="Tool to uninstall skill from",
        shell_complete=complete_tool_name,
    ),
    level: str = typer.Option(
        "user",
        "--level",
        "-l",
        help="Uninstall from user or project level",
    ),
) -> None:
    """
    Remove installed NotebookLM skill.

    Examples:
        nlm skill uninstall claude-code
        nlm skill uninstall codex --level project
    """
    if level not in ("user", "project"):
        console.print(f"[red]Error:[/red] Invalid level '{level}'. Must be 'user' or 'project'.")
        raise typer.Exit(1)

    if tool not in TOOL_CONFIGS:
        valid_tools = ", ".join(TOOL_CONFIGS.keys())
        console.print(f"[red]Error:[/red] Unknown tool '{tool}'")
        console.print(f"Valid tools: {valid_tools}")
        raise typer.Exit(1)

    is_installed, install_path = check_install_status(tool, level)

    if not is_installed:
        console.print(f"[yellow]![/yellow] Skill not installed for {tool} at {level} level")
        raise typer.Exit(0)

    # Confirm deletion
    if not typer.confirm(f"Remove skill from {install_path}?"):
        console.print("Cancelled.")
        raise typer.Exit(0)

    config = TOOL_CONFIGS[tool]
    format_type = config["format"]

    try:
        if format_type == "skill.md":
            # Remove directory
            if install_path.exists():
                shutil.rmtree(install_path)
            console.print(f"[green]✓[/green] Removed {install_path}")

        elif format_type == "agents.md":
            # Remove section from AGENTS.md
            if install_path.exists():
                content = install_path.read_text(encoding="utf-8")
                start_marker = "<!-- nlm-skill-start -->"
                end_marker = "<!-- nlm-skill-end -->"

                start_idx = content.find(start_marker)
                end_idx = content.find(end_marker)

                if start_idx != -1 and end_idx != -1:
                    # Remove section
                    before = content[:start_idx].rstrip()
                    after = content[end_idx + len(end_marker) :].lstrip()

                    if before and after:
                        content = before + "\n\n" + after
                    elif before:
                        content = before
                    elif after:
                        content = after
                    else:
                        content = ""

                    install_path.write_text(content, encoding="utf-8")
                    console.print(f"[green]✓[/green] Removed NLM section from {install_path}")
                else:
                    console.print(f"[yellow]![/yellow] Markers not found in {install_path}")

        elif format_type == "all":
            # Remove export directory
            if install_path.exists():
                shutil.rmtree(install_path)
            console.print(f"[green]✓[/green] Removed {install_path}")

    except Exception as e:
        console.print(f"\n[red]✗ Uninstall failed:[/red] {e}")
        raise typer.Exit(1) from e


@app.command("list")
def list_tools() -> None:
    """
    Show available tools and installation status.
    """
    table = Table(title="NotebookLM Skill Installation Status")
    table.add_column("Tool", style="cyan")
    table.add_column("Description")
    table.add_column("User", justify="center")
    table.add_column("Project", justify="center")

    has_outdated = False

    for tool, config in TOOL_CONFIGS.items():
        # Skip "other" — it's an export format, not a real install target
        if tool == "other":
            continue

        # Check user level
        user_status = ""
        if "user" in config:
            is_installed, _ = check_install_status(tool, "user")
            if is_installed:
                installed_ver = _get_installed_version(tool, "user")
                if installed_ver is None:
                    user_status = "[yellow]✓ (unknown)[/yellow]"
                    has_outdated = True
                elif installed_ver != __version__:
                    user_status = f"[yellow]✓ (v{installed_ver})[/yellow]"
                    has_outdated = True
                else:
                    user_status = "[green]✓[/green]"
            else:
                user_status = "[dim]-[/dim]"
        else:
            user_status = "[dim]N/A[/dim]"

        # Check project level
        project_status = ""
        if "project" in config:
            is_installed, _ = check_install_status(tool, "project")
            if is_installed:
                installed_ver = _get_installed_version(tool, "project")
                if installed_ver is None:
                    project_status = "[yellow]✓ (unknown)[/yellow]"
                    has_outdated = True
                elif installed_ver != __version__:
                    project_status = f"[yellow]✓ (v{installed_ver})[/yellow]"
                    has_outdated = True
                else:
                    project_status = "[green]✓[/green]"
            else:
                project_status = "[dim]-[/dim]"
        else:
            project_status = "[dim]N/A[/dim]"

        table.add_row(
            tool,
            config["description"],
            user_status,
            project_status,
        )

    console.print(table)
    console.print("\n[dim]Legend: ✓ = installed, - = not installed, N/A = not applicable[/dim]")
    if has_outdated:
        console.print(
            f"[yellow]⚠  Some skills are outdated (current: v{__version__}). Run 'nlm skill update' to update all.[/yellow]"
        )


def _update_single_tool(tool: str, level: str) -> bool:
    """Update a single tool's skill at the given level. Returns True if updated."""
    config = TOOL_CONFIGS[tool]
    install_path = config.get(level)
    if not install_path:
        return False

    format_type = config["format"]

    try:
        if format_type == "skill.md":
            install_skill_md(install_path, config.get("frontmatter_extras"))
        elif format_type == "agents.md":
            install_agents_md(install_path)
        elif format_type == "all":
            install_all_formats(install_path)
        return True
    except Exception as e:
        console.print(f"[red]Error updating {tool} ({level}):[/red] {e}")
        return False


@app.command("update")
def update(
    tool: str | None = typer.Argument(
        None,
        help="Tool to update (omit to update all outdated skills)",
        shell_complete=complete_tool_name,
    ),
) -> None:
    """
    Update outdated skills to the current version.

    Examples:
        nlm skill update              # Update all outdated skills
        nlm skill update claude-code  # Update just Claude Code
    """
    if tool and tool not in TOOL_CONFIGS:
        valid_tools = ", ".join(TOOL_CONFIGS.keys())
        console.print(f"[red]Error:[/red] Unknown tool '{tool}'")
        console.print(f"Valid tools: {valid_tools}")
        raise typer.Exit(1)

    tools_to_check = {tool: TOOL_CONFIGS[tool]} if tool else TOOL_CONFIGS
    updated = 0
    skipped = 0
    already_current = 0

    for t, config in tools_to_check.items():
        for level in ("user", "project"):
            if level not in config:
                continue

            is_installed, _ = check_install_status(t, level)
            if not is_installed:
                continue

            installed_ver = _get_installed_version(t, level)
            if installed_ver == __version__:
                already_current += 1
                if tool:
                    # Only show this message when updating a specific tool
                    console.print(f"[green]✓[/green] {t} ({level}) is already at v{__version__}")
                continue

            old_ver = installed_ver or "unknown"
            console.print(f"\n[bold]Updating {t} ({level}):[/bold] v{old_ver} → v{__version__}")
            if _update_single_tool(t, level):
                updated += 1
            else:
                skipped += 1

    # Summary
    console.print()
    if updated == 0 and already_current > 0 and skipped == 0:
        console.print(f"[green]All installed skills are already at v{__version__} ✓[/green]")
    elif updated > 0:
        console.print(f"[green]✓ Updated {updated} skill(s) to v{__version__}[/green]")
        if skipped > 0:
            console.print(f"[yellow]⚠ {skipped} skill(s) failed to update[/yellow]")
    elif skipped > 0:
        console.print(f"[red]✗ {skipped} skill(s) failed to update[/red]")
    else:
        if tool:
            console.print(
                f"[dim]{tool} is not installed. Use 'nlm skill install {tool}' first.[/dim]"
            )
        else:
            console.print("[dim]No installed skills found to update.[/dim]")


@app.command("show")
def show() -> None:
    """
    Display the NotebookLM skill content.
    """
    data_dir = get_data_dir()
    skill_file = data_dir / "SKILL.md"

    if not skill_file.exists():
        console.print("[red]Error:[/red] SKILL.md not found")
        raise typer.Exit(1)

    content = skill_file.read_text(encoding="utf-8")
    console.print(content)
