"""MCP server setup commands for AI tool clients.

Configures the Gemini Notebook MCP server in various AI tool config files,
so the tools can use Gemini Notebook via MCP protocol.

This is different from `nlm skill` which installs skill/reference docs.
`nlm setup` configures the actual MCP server transport.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import typer
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from notebooklm_tools.cli.utils import is_tool_on_system, make_console

console = make_console()
app = typer.Typer(
    name="setup",
    help="Configure Gemini Notebook MCP server for AI tools",
    no_args_is_help=True,
)

# MCP server identifier used in client configuration files.
MCP_SERVER_NAME = "gemini-notebook-mcp"

# The executable remains unchanged for compatibility with existing installs.
MCP_SERVER_CMD = "notebooklm-mcp"

# Older releases used these server names. Recognize them for migration and
# removal, but never write them into new configuration.
LEGACY_MCP_SERVER_NAMES = ("notebooklm-mcp", "notebooklm")
MCP_SERVER_NAMES = (MCP_SERVER_NAME, *LEGACY_MCP_SERVER_NAMES)

# Default MCP tool call timeout in milliseconds (5 minutes).
# NotebookLM operations (query, source add, research, studio) can take 60-120+ seconds.
# OpenCode's default MCP SDK timeout is 60s, which is too short.
OPENCODE_MCP_TIMEOUT_MS = 300_000

CLAUDE_DESKTOP_PROFILE_REGULAR = "regular"
CLAUDE_DESKTOP_PROFILE_3P = "3p"
CLAUDE_DESKTOP_PROFILE_BOTH = "both"
CLAUDE_DESKTOP_PROFILES = (
    CLAUDE_DESKTOP_PROFILE_REGULAR,
    CLAUDE_DESKTOP_PROFILE_3P,
)


def _find_mcp_server_path() -> str | None:
    """Find the full path to the notebooklm-mcp binary."""
    return shutil.which(MCP_SERVER_CMD)


def _read_json_config(path: Path) -> dict:
    """Read a JSON config file, returning empty dict if missing or invalid."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json_config(path: Path, config: dict) -> None:
    """Write a JSON config file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")


def _entry_command_tokens(entry: object) -> list[str]:
    """Return command and argument tokens from a client MCP entry."""
    if not isinstance(entry, dict):
        return []
    command = entry.get("command")
    if isinstance(command, str):
        tokens = [command]
    elif isinstance(command, list):
        tokens = [str(token) for token in command]
    else:
        tokens = []
    args = entry.get("args")
    if isinstance(args, list):
        tokens.extend(str(token) for token in args)
    return tokens


def _is_our_mcp_entry(name: str, entry: object) -> bool:
    """Identify this project's MCP entry without claiming unrelated servers."""
    if name == MCP_SERVER_NAME or name == "notebooklm-mcp":
        return True
    if name != "notebooklm":
        return False

    for token in _entry_command_tokens(entry):
        normalized = token.replace("\\", "/").lower()
        if normalized.rsplit("/", 1)[-1] == MCP_SERVER_CMD:
            return True
        if token.lower() in {"notebooklm-mcp-cli", MCP_SERVER_CMD}:
            return True
    return False


def _configured_mcp_names(servers: object) -> list[str]:
    """Return recognized Gemini Notebook MCP names in a config mapping."""
    if not isinstance(servers, dict):
        return []
    return [name for name, entry in servers.items() if _is_our_mcp_entry(name, entry)]


def _is_configured(config: dict, key: str = MCP_SERVER_NAME) -> bool:
    """Check if this project's MCP is configured in an ``mcpServers`` mapping."""
    del key  # Retained for compatibility with callers that specify a preferred key.
    return bool(_configured_mcp_names(config.get("mcpServers", {})))


def _remove_mcp_entries(servers: object) -> bool:
    """Remove only recognized Gemini Notebook MCP entries from a mapping."""
    if not isinstance(servers, dict):
        return False
    names = _configured_mcp_names(servers)
    for name in names:
        del servers[name]
    return bool(names)


def _migrate_legacy_mcp_entry(config: dict, container_key: str) -> bool:
    """Rename one recognized legacy entry to the current branded name."""
    servers = config.get(container_key, {})
    if not isinstance(servers, dict) or MCP_SERVER_NAME in servers:
        return False

    for name in _configured_mcp_names(servers):
        if name in LEGACY_MCP_SERVER_NAMES:
            servers[MCP_SERVER_NAME] = servers.pop(name)
            return True
    return False


def _cli_output_contains_mcp(output: str) -> bool:
    """Check CLI output for the current or a known legacy server name."""
    lower_output = output.lower()
    return any(
        re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", lower_output)
        for name in MCP_SERVER_NAMES
    )


def _add_mcp_server(config: dict, key: str = MCP_SERVER_NAME, extra: dict | None = None) -> dict:
    """Add Gemini Notebook MCP to an ``mcpServers`` config dict."""
    config.setdefault("mcpServers", {})
    entry = {"command": MCP_SERVER_CMD, "args": []}
    if extra:
        entry.update(extra)
    config["mcpServers"][key] = entry
    return config


def _is_vscode_mcp_configured(config: dict, key: str = MCP_SERVER_NAME) -> bool:
    """Check if Gemini Notebook MCP is in a VS Code/Copilot ``servers`` config."""
    del key
    return bool(_configured_mcp_names(config.get("servers", {})))


def _add_vscode_mcp_server(
    config: dict, key: str = MCP_SERVER_NAME, extra: dict | None = None
) -> dict:
    """Add Gemini Notebook MCP to a VS Code/Copilot ``servers`` config dict."""
    config.setdefault("servers", {})
    entry = {"command": MCP_SERVER_CMD, "args": []}
    if extra:
        entry.update(extra)
    config["servers"][key] = entry
    return config


# =============================================================================
# Client-specific config paths
# =============================================================================


def _gemini_config_path() -> Path:
    """Get Gemini CLI config path."""
    return Path.home() / ".gemini" / "settings.json"


def _cursor_config_path(level: str = "user") -> Path:
    """Get Cursor MCP config path."""
    if level == "project":
        return Path(".cursor") / "mcp.json"
    # User-level
    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".cursor" / "mcp.json"
    elif system == "Windows":
        appdata = Path(os.environ.get("APPDATA", ""))
        return appdata / "Cursor" / "User" / "mcp.json"
    else:
        return Path.home() / ".config" / "cursor" / "mcp.json"


def _windsurf_config_path() -> Path:
    """Get Windsurf MCP config path."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
    elif system == "Windows":
        appdata = Path(os.environ.get("APPDATA", ""))
        return appdata / "Codeium" / "windsurf" / "mcp_config.json"
    else:
        return Path.home() / ".config" / "codeium" / "windsurf" / "mcp_config.json"


def _cline_config_path() -> Path:
    """Get Cline CLI MCP settings path.

    This is the standalone CLI path, NOT the VS Code extension path.
    """
    return Path.home() / ".cline" / "data" / "settings" / "cline_mcp_settings.json"


def _antigravity_config_path() -> Path:
    """Get Google Antigravity MCP config path."""
    return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"


def _codex_config_path() -> Path:
    """Get Codex CLI config directory path."""
    return Path.home() / ".codex"


def _opencode_config_path() -> Path:
    """Get OpenCode global config path."""
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _github_copilot_config_path() -> Path:
    """Get GitHub Copilot workspace MCP config path."""
    return Path(".vscode") / "mcp.json"


def _claude_desktop_msix_package_dir() -> Path | None:
    """Find the installed Claude Desktop MSIX package directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    packages_dir = Path(local_app_data) / "Packages"
    if not packages_dir.is_dir():
        return None

    package_dirs = sorted(
        (
            path
            for path in packages_dir.iterdir()
            if path.is_dir()
            and (
                path.name.lower().startswith("claude_")
                or path.name.lower().startswith("anthropic.claude")
            )
        ),
        key=lambda path: path.name.lower(),
    )
    if len(package_dirs) != 1:
        return None

    return package_dirs[0]


def _claude_desktop_msix_config_path() -> Path | None:
    """Find the config path used by a Claude Desktop MSIX installation."""
    package_dir = _claude_desktop_msix_package_dir()
    if package_dir is None:
        return None
    return package_dir / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"


def _claude_desktop_candidate_paths() -> dict[str, Path]:
    """Return regular and Relay AI/3P Claude Desktop config candidates."""
    system = platform.system()
    if system == "Darwin":
        app_support = Path.home() / "Library" / "Application Support"
        return {
            CLAUDE_DESKTOP_PROFILE_REGULAR: app_support / "Claude" / "claude_desktop_config.json",
            CLAUDE_DESKTOP_PROFILE_3P: app_support / "Claude-3p" / "claude_desktop_config.json",
        }

    if system == "Windows":
        regular_path = _claude_desktop_msix_config_path()
        if regular_path is None:
            appdata = os.environ.get("APPDATA")
            appdata_path = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
            regular_path = appdata_path / "Claude" / "claude_desktop_config.json"

        local_app_data = os.environ.get("LOCALAPPDATA")
        local_app_data_path = (
            Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
        )
        return {
            CLAUDE_DESKTOP_PROFILE_REGULAR: regular_path,
            CLAUDE_DESKTOP_PROFILE_3P: local_app_data_path
            / "Claude-3p"
            / "claude_desktop_config.json",
        }

    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return {
        CLAUDE_DESKTOP_PROFILE_REGULAR: config_home / "Claude" / "claude_desktop_config.json",
        CLAUDE_DESKTOP_PROFILE_3P: config_home / "Claude-3p" / "claude_desktop_config.json",
    }


def _claude_desktop_profile_exists(profile: str, config_path: Path) -> bool:
    """Return whether a Claude Desktop profile is present to receive config."""
    if config_path.exists() or config_path.parent.exists():
        return True

    # An MSIX package proves regular Claude Desktop is installed even when it
    # has not created its per-user config directory yet.
    return (
        profile == CLAUDE_DESKTOP_PROFILE_REGULAR
        and platform.system() == "Windows"
        and _claude_desktop_msix_config_path() == config_path
        and _claude_desktop_msix_package_dir() is not None
    )


def _claude_desktop_profile_paths() -> dict[str, Path]:
    """Return only Claude Desktop profiles detected on this system."""
    candidates = _claude_desktop_candidate_paths()
    return {
        profile: path
        for profile, path in candidates.items()
        if _claude_desktop_profile_exists(profile, path)
    }


def _claude_desktop_process_list() -> str:
    """Return the running Claude Desktop process command lines."""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='Claude.exe' OR Name='claude.exe'\" "
                    "| Select-Object -ExpandProperty CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        else:
            result = subprocess.run(
                ["ps", "-axo", "command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout


def _is_claude_desktop_process_line(line: str) -> bool:
    """Return whether a process line belongs to the Claude Desktop executable."""
    normalized = line.lower()
    return any(
        marker in normalized
        for marker in (
            "claude.app/contents/macos/claude",
            "claude.exe",
            "claude-desktop",
            "claude desktop",
        )
    )


def _claude_desktop_profile_is_running(
    profile: str, config_path: Path | None = None, process_list: str | None = None
) -> bool:
    """Return whether a selected Claude Desktop profile is currently running."""
    if profile not in CLAUDE_DESKTOP_PROFILES:
        return False

    # Ignore synthetic paths supplied by callers/tests; only guard the paths
    # this command would actually select on the current machine.
    if config_path is not None and _claude_desktop_candidate_paths().get(profile) != config_path:
        return False

    snapshot = _claude_desktop_process_list() if process_list is None else process_list
    lines = [line for line in snapshot.splitlines() if line]
    claude_lines = [line.lower() for line in lines if _is_claude_desktop_process_line(line)]
    if not claude_lines:
        return False

    running_3p = any("claude-3p" in line or "claude_3p" in line for line in claude_lines)
    return running_3p if profile == CLAUDE_DESKTOP_PROFILE_3P else not running_3p


def _ensure_claude_desktop_profiles_stopped(selected: dict[str, Path]) -> bool:
    """Prevent config writes while Claude Desktop can overwrite them."""
    running = [
        profile
        for profile, config_path in selected.items()
        if _claude_desktop_profile_is_running(profile, config_path)
    ]
    if not running:
        return True

    labels = ", ".join(
        "Relay AI / Claude 3P" if profile == CLAUDE_DESKTOP_PROFILE_3P else "regular Claude Desktop"
        for profile in running
    )
    console.print(
        f"[yellow]Claude Desktop is still running ({labels}). "
        "No configuration was changed.[/yellow]"
    )
    console.print(
        "[yellow]Fully quit that Claude instance, then run this command again "
        "before reopening it.[/yellow]"
    )
    return False


def _claude_desktop_config_path() -> Path:
    """Get the Claude Desktop MCP config path for the current platform."""
    candidates = _claude_desktop_candidate_paths()
    preferred = (
        CLAUDE_DESKTOP_PROFILE_3P
        if platform.system() == "Darwin"
        else CLAUDE_DESKTOP_PROFILE_REGULAR
    )
    return candidates[preferred]


# =============================================================================
# Client definitions
# =============================================================================

CLIENT_REGISTRY = {
    "claude-code": {
        "name": "Claude Code",
        "description": "Anthropic CLI (claude command)",
        "has_auto_setup": True,
    },
    "claude-desktop": {
        "name": "Claude Desktop",
        "description": "Anthropic Claude Desktop app",
        "has_auto_setup": True,
    },
    "gemini": {
        "name": "Gemini CLI",
        "description": "Google Gemini CLI",
        "has_auto_setup": True,
    },
    "cursor": {
        "name": "Cursor",
        "description": "Cursor AI editor",
        "has_auto_setup": True,
    },
    "github-copilot": {
        "name": "GitHub Copilot",
        "description": "GitHub Copilot in VS Code (workspace)",
        "has_auto_setup": True,
    },
    "windsurf": {
        "name": "Windsurf",
        "description": "Codeium Windsurf editor",
        "has_auto_setup": True,
    },
    "cline": {
        "name": "Cline CLI",
        "description": "Cline CLI terminal agent",
        "has_auto_setup": True,
    },
    "antigravity": {
        "name": "Antigravity",
        "description": "Google Antigravity AI IDE",
        "has_auto_setup": True,
    },
    "codex": {
        "name": "Codex CLI",
        "description": "OpenAI Codex CLI",
        "has_auto_setup": True,
    },
    "opencode": {
        "name": "OpenCode",
        "description": "OpenCode terminal AI assistant",
        "has_auto_setup": True,
    },
}

CLIENT_ALIASES = {
    "copilot": "github-copilot",
}


def _complete_client(ctx, param, incomplete: str) -> list[str]:
    """Shell completion for client names."""
    all_clients = list(CLIENT_REGISTRY.keys()) + list(CLIENT_ALIASES.keys()) + ["json", "all"]
    return [name for name in all_clients if name.startswith(incomplete)]


# =============================================================================
# Setup implementations
# =============================================================================


def _setup_claude_code() -> bool:
    """Add Gemini Notebook MCP to Claude Code via `claude mcp add`."""
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print("[yellow]Warning:[/yellow] 'claude' command not found in PATH")
        console.print("  Install Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        console.print()
        console.print("  Manual setup — add to [dim]~/.claude/settings.json[/dim]:")
        console.print(
            f'    "mcpServers": {{ "{MCP_SERVER_NAME}": {{ "command": "{MCP_SERVER_CMD}" }} }}'
        )
        return False

    try:
        result = subprocess.run(
            [claude_cmd, "mcp", "add", "-s", "user", MCP_SERVER_NAME, "--", MCP_SERVER_CMD],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            console.print("[green]✓[/green] Added to Claude Code (user scope)")
            return True
        elif "already exists" in result.stderr.lower():
            console.print("[green]✓[/green] Already configured in Claude Code")
            return True
        else:
            console.print(
                f"[yellow]Warning:[/yellow] claude mcp add returned: {result.stderr.strip()}"
            )
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        console.print(f"[yellow]Warning:[/yellow] Could not run claude command: {e}")
        return False


def _select_claude_desktop_profile_paths(
    profile: str | None = None, *, configured_only: bool = False
) -> dict[str, Path]:
    """Select Claude Desktop profiles for MCP setup or removal."""
    detected = _claude_desktop_profile_paths()
    if not detected:
        console.print(
            "[yellow]Claude Desktop was not detected on this system. "
            "No configuration was changed.[/yellow]"
        )
        return {}

    if configured_only:
        detected = {
            profile_name: config_path
            for profile_name, config_path in detected.items()
            if _is_configured(_read_json_config(config_path))
        }
        if not detected:
            console.print(
                "[dim]No detected Claude Desktop profile contains "
                f"{MCP_SERVER_NAME}. No configuration was changed.[/dim]"
            )
            return {}

    if profile is not None:
        profile = profile.lower()
        if profile not in (*CLAUDE_DESKTOP_PROFILES, CLAUDE_DESKTOP_PROFILE_BOTH):
            console.print(
                "[red]Error:[/red] Invalid Claude Desktop profile. "
                "Choose 'regular', '3p', or 'both'."
            )
            return {}
        if profile == CLAUDE_DESKTOP_PROFILE_BOTH:
            missing = [name for name in CLAUDE_DESKTOP_PROFILES if name not in detected]
            if missing:
                console.print(f"[dim]Skipping undetected profile(s): {', '.join(missing)}.[/dim]")
            return detected
        if profile not in detected:
            console.print(
                f"[yellow]Claude Desktop profile '{profile}' was not detected or does not contain "
                f"{MCP_SERVER_NAME}. "
                "No configuration was changed.[/yellow]"
            )
            return {}
        return {profile: detected[profile]}

    if len(detected) == 1:
        return detected

    options = [
        (
            CLAUDE_DESKTOP_PROFILE_REGULAR,
            f"Regular Claude Desktop — {detected[CLAUDE_DESKTOP_PROFILE_REGULAR]}",
        ),
        (
            CLAUDE_DESKTOP_PROFILE_3P,
            f"Relay AI / Claude 3P — {detected[CLAUDE_DESKTOP_PROFILE_3P]}",
        ),
        (CLAUDE_DESKTOP_PROFILE_BOTH, "Both detected profiles"),
    ]
    selected = _prompt_numbered(
        "Multiple Claude Desktop profiles detected:",
        options,
    )
    if selected == CLAUDE_DESKTOP_PROFILE_BOTH:
        return detected
    return {selected: detected[selected]}


def _setup_claude_desktop(profile: str | None = None) -> bool:
    """Add Gemini Notebook MCP to one or more detected Claude Desktop profiles.

    Claude Desktop launches servers without inheriting the user's shell
    PATH, so the bare command name often fails to resolve. We write the
    full resolved path to the notebooklm-mcp binary instead.

    No config directory is created unless the corresponding Claude Desktop
    profile is already detected. When both profiles exist, an interactive
    invocation asks which profile(s) should receive the MCP.
    """
    selected = _select_claude_desktop_profile_paths(profile)
    if not selected:
        return False
    if not _ensure_claude_desktop_profiles_stopped(selected):
        return False

    pending: list[tuple[str, Path, dict]] = []
    for profile_name, config_path in selected.items():
        config = _read_json_config(config_path)
        migrated = _migrate_legacy_mcp_entry(config, "mcpServers")
        if migrated:
            _write_json_config(config_path, config)
            console.print(
                f"[green]✓[/green] Updated Claude Desktop ({profile_name}) to {MCP_SERVER_NAME}"
            )
        if _is_configured(config):
            console.print(f"[green]✓[/green] Already configured in Claude Desktop ({profile_name})")
        else:
            pending.append((profile_name, config_path, config))

    if not pending:
        return True

    binary_path = _find_mcp_server_path()
    if not binary_path:
        console.print(
            "[red]Error:[/red] notebooklm-mcp was not found in PATH. "
            "Install it first or add its full path to Claude Desktop manually."
        )
        console.print("  Find the installed binary with: [dim]which notebooklm-mcp[/dim]")
        return False

    for profile_name, config_path, config in pending:
        _add_mcp_server(config, extra={"command": binary_path})
        _write_json_config(config_path, config)
        console.print(f"[green]✓[/green] Added to Claude Desktop ({profile_name})")
        console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_gemini() -> bool:
    """Add MCP to Gemini CLI config."""
    config_path = _gemini_config_path()
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "mcpServers")
    if _is_configured(config):
        if migrated:
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Updated Gemini CLI to {MCP_SERVER_NAME}")
        else:
            console.print("[green]✓[/green] Already configured in Gemini CLI")
        return True

    console.print(
        "[yellow]Note:[/yellow] Gemini CLI requires [bold]trust: true[/bold] for this MCP "
        "server to function. This grants the server permission to run shell commands and "
        "access files without per-action prompts."
    )
    if not Confirm.ask(f"Grant elevated trust to {MCP_SERVER_NAME} in Gemini CLI?", default=True):
        console.print("[yellow]Skipped.[/yellow] Re-run setup to add trust later.")
        return False

    _add_mcp_server(config, extra={"trust": True})
    _write_json_config(config_path, config)
    console.print("[green]✓[/green] Added to Gemini CLI")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_github_copilot() -> bool:
    """Add MCP to GitHub Copilot's workspace MCP config."""
    config_path = _github_copilot_config_path()
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "servers")
    if _is_vscode_mcp_configured(config):
        if migrated:
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Updated GitHub Copilot to {MCP_SERVER_NAME}")
        else:
            console.print("[green]✓[/green] Already configured in GitHub Copilot")
        return True

    _add_vscode_mcp_server(config)
    _write_json_config(config_path, config)
    console.print("[green]✓[/green] Added to GitHub Copilot (workspace)")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_cursor(level: str = "user") -> bool:
    """Add MCP to Cursor config."""
    config_path = _cursor_config_path(level)
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "mcpServers")
    if _is_configured(config):
        if migrated:
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Updated Cursor ({level}) to {MCP_SERVER_NAME}")
        else:
            console.print(f"[green]✓[/green] Already configured in Cursor ({level})")
        return True

    _add_mcp_server(config)
    _write_json_config(config_path, config)
    console.print(f"[green]✓[/green] Added to Cursor ({level})")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_windsurf() -> bool:
    """Add MCP to Windsurf config."""
    config_path = _windsurf_config_path()
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "mcpServers")
    if _is_configured(config):
        if migrated:
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Updated Windsurf to {MCP_SERVER_NAME}")
        else:
            console.print("[green]✓[/green] Already configured in Windsurf")
        return True

    _add_mcp_server(config)
    _write_json_config(config_path, config)
    console.print("[green]✓[/green] Added to Windsurf")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_cline() -> bool:
    """Add MCP to Cline CLI config."""
    config_path = _cline_config_path()
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "mcpServers")
    if _is_configured(config):
        if migrated:
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Updated Cline CLI to {MCP_SERVER_NAME}")
        else:
            console.print("[green]✓[/green] Already configured in Cline CLI")
        return True

    _add_mcp_server(config)
    _write_json_config(config_path, config)
    console.print("[green]✓[/green] Added to Cline CLI")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_antigravity() -> bool:
    """Add MCP to Google Antigravity config."""
    config_path = _antigravity_config_path()
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "mcpServers")
    if _is_configured(config):
        if migrated:
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Updated Antigravity to {MCP_SERVER_NAME}")
        else:
            console.print("[green]✓[/green] Already configured in Antigravity")
        return True

    _add_mcp_server(config)
    _write_json_config(config_path, config)
    console.print("[green]✓[/green] Added to Antigravity")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _setup_codex() -> bool:
    """Add MCP to Codex CLI via `codex mcp add` (preferred) or config.toml fallback."""
    codex_cmd = shutil.which("codex")
    if codex_cmd:
        try:
            result = subprocess.run(
                [codex_cmd, "mcp", "add", MCP_SERVER_NAME, "--", MCP_SERVER_CMD],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                console.print("[green]✓[/green] Added to Codex CLI")
                return True
            elif "already exists" in result.stderr.lower():
                console.print("[green]✓[/green] Already configured in Codex CLI")
                return True
            else:
                console.print(
                    f"[yellow]Warning:[/yellow] codex mcp add returned: {result.stderr.strip()}"
                )
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            console.print(f"[yellow]Warning:[/yellow] Could not run codex command: {e}")
            return False
    else:
        # Fallback: write config.toml directly
        config_path = _codex_config_path() / "config.toml"

        if config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8")
                config = tomllib.loads(content)
                mcp_servers = config.get("mcp_servers", {})
                if _configured_mcp_names(mcp_servers):
                    console.print("[green]✓[/green] Already configured in Codex CLI")
                    return True
            except Exception:
                content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        else:
            content = ""

        section = """
# Gemini Notebook MCP server
[mcp_servers.gemini-notebook-mcp]
command = "notebooklm-mcp"
args = []
enabled = true
"""
        new_content = content.rstrip() + "\n" + section if content.strip() else section.lstrip()

        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(new_content, encoding="utf-8")
        console.print("[green]✓[/green] Added to Codex CLI (config.toml)")
        console.print(f"  [dim]{config_path}[/dim]")
        return True


def _setup_opencode() -> bool:
    """Add MCP to OpenCode config.

    Configures both the MCP server entry and a global ``experimental.mcp_timeout``
    so that long-running NotebookLM operations (query, source add, research, studio)
    don't hit OpenCode's default 60-second MCP request timeout.
    """
    config_path = _opencode_config_path()
    config = _read_json_config(config_path)

    migrated = _migrate_legacy_mcp_entry(config, "mcp")
    mcp = config.get("mcp", {})
    if _configured_mcp_names(mcp):
        # Still ensure timeout is set even if server entry already exists
        _ensure_opencode_timeout(config)
        if migrated:
            console.print(f"[green]✓[/green] Updated OpenCode to {MCP_SERVER_NAME}")
        else:
            console.print("[green]✓[/green] Already configured in OpenCode")
        _write_json_config(config_path, config)
        return True

    mcp[MCP_SERVER_NAME] = {
        "type": "local",
        "command": [MCP_SERVER_CMD],
        "enabled": True,
        "timeout": OPENCODE_MCP_TIMEOUT_MS,
    }
    config["mcp"] = mcp

    # Set global experimental timeout (proven reliable across OpenCode versions)
    _ensure_opencode_timeout(config)

    _write_json_config(config_path, config)
    console.print("[green]✓[/green] Added to OpenCode")
    console.print(f"  [dim]{config_path}[/dim]")
    return True


def _ensure_opencode_timeout(config: dict) -> None:
    """Set ``experimental.mcp_timeout`` if not already present.

    The per-server ``timeout`` field is reportedly unreliable in some OpenCode
    versions, so we also set the global experimental timeout as a fallback.
    Only writes the value if the user hasn't already set a custom timeout.
    """
    experimental = config.setdefault("experimental", {})
    if "mcp_timeout" not in experimental:
        experimental["mcp_timeout"] = OPENCODE_MCP_TIMEOUT_MS


def _detect_tool(client_id: str) -> bool:
    """Check if an AI tool is installed/present on the system.

    Delegates to the shared ``is_tool_on_system`` helper with per-client
    binary names and root config directories.
    """
    _home = Path.home()
    if client_id == "claude-desktop":
        return bool(_claude_desktop_profile_paths())

    detection: dict[str, tuple[str | None, list[Path]]] = {
        "claude-code": ("claude", [_home / ".claude"]),
        "gemini": ("gemini", [_gemini_config_path().parent]),
        "cursor": ("cursor", [_home / ".cursor"]),
        "github-copilot": ("code", [_github_copilot_config_path().parent]),
        "windsurf": (None, [_windsurf_config_path().parent]),
        "cline": ("cline", [_home / ".cline"]),
        "antigravity": (None, [_antigravity_config_path().parent]),
        "codex": ("codex", [_codex_config_path()]),
        "opencode": ("opencode", [_opencode_config_path()]),
    }
    entry = detection.get(client_id)
    if not entry:
        return False
    try:
        return is_tool_on_system(binary=entry[0], root_dirs=entry[1])
    except Exception:
        return False


def _is_already_configured(client_id: str) -> bool:
    """Check if MCP is already configured for a client."""
    try:
        if client_id == "claude-code":
            claude_cmd = shutil.which("claude")
            if claude_cmd:
                result = subprocess.run(
                    [claude_cmd, "mcp", "list"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return _cli_output_contains_mcp(result.stdout)
            return False

        elif client_id == "claude-desktop":
            paths = _claude_desktop_profile_paths()
            return bool(paths) and all(
                _is_configured(_read_json_config(path)) for path in paths.values()
            )
        elif client_id == "gemini":
            config = _read_json_config(_gemini_config_path())
            return _is_configured(config)
        elif client_id == "github-copilot":
            config = _read_json_config(_github_copilot_config_path())
            return _is_vscode_mcp_configured(config)
        elif client_id == "cursor":
            config = _read_json_config(_cursor_config_path())
            return _is_configured(config)
        elif client_id == "windsurf":
            config = _read_json_config(_windsurf_config_path())
            return _is_configured(config)
        elif client_id == "cline":
            config = _read_json_config(_cline_config_path())
            return _is_configured(config)
        elif client_id == "antigravity":
            config = _read_json_config(_antigravity_config_path())
            return _is_configured(config)
        elif client_id == "codex":
            codex_cmd = shutil.which("codex")
            if codex_cmd:
                result = subprocess.run(
                    [codex_cmd, "mcp", "list"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return _cli_output_contains_mcp(result.stdout)
            else:
                # Check config.toml directly
                toml_path = _codex_config_path() / "config.toml"
                if toml_path.exists():
                    config = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                    mcp = config.get("mcp_servers", {})
                    return bool(_configured_mcp_names(mcp))
        elif client_id == "opencode":
            config = _read_json_config(_opencode_config_path())
            mcp = config.get("mcp", {})
            return bool(_configured_mcp_names(mcp))
    except Exception:
        pass
    return False


def _setup_all() -> None:
    """Interactive multi-tool setup. Scans system for AI tools and lets user choose."""
    console.print("\n[bold]Scanning for AI tools...[/bold]\n")

    # Scan ALL tools (auto-setup and manual)
    detected = []  # (client_id, info, is_configured, has_auto)
    not_found = []

    for client_id, info in CLIENT_REGISTRY.items():
        is_present = _detect_tool(client_id)
        if is_present:
            has_auto = info["has_auto_setup"]
            already = _is_already_configured(client_id) if has_auto else False
            detected.append((client_id, info, already, has_auto))
        else:
            not_found.append((client_id, info))

    # Display results table
    table = Table(title="Detected AI Tools")
    table.add_column("#", justify="right", style="cyan", width=3)
    table.add_column("Tool", style="bold")
    table.add_column("Status", justify="center")

    configurable = []  # indices of tools that can be auto-configured
    for i, (client_id, info, already, has_auto) in enumerate(detected):  # noqa: B007
        num = str(i + 1)
        if not has_auto:
            table.add_row(num, info["name"], "[dim]use nlm skill install[/dim]")
        elif already:
            table.add_row(num, info["name"], "[green]✓ configured[/green]")
        else:
            table.add_row(num, info["name"], "[yellow]detected[/yellow]")
            configurable.append(i)

    console.print(table)

    if not_found:
        names = ", ".join(info["name"] for _, info in not_found)
        console.print(f"\n[dim]Not found: {names}[/dim]")

    if not configurable:
        if detected:
            console.print("\n[green]All detected tools are already configured! ✓[/green]")
        else:
            console.print("\n[yellow]No supported AI tools detected on your system.[/yellow]")
            console.print("[dim]Use 'nlm setup add <client>' to configure a specific tool.[/dim]")
        return

    # Interactive selection
    unconfigured_names = [f"{detected[i][1]['name']} ({detected[i][0]})" for i in configurable]
    console.print(f"\n[bold]Unconfigured tools:[/bold] {', '.join(unconfigured_names)}")
    console.print()

    choice = (
        Prompt.ask(
            "Configure which tools? [cyan]all/yes[/cyan] / comma-separated numbers / [cyan]none[/cyan]",
            default="all",
        )
        .strip()
        .lower()
    )

    if choice == "none" or choice == "n":
        console.print("Cancelled.")
        return

    # Determine which tools to configure
    if choice == "all" or choice == "a" or choice == "yes" or choice == "y":
        selected_indices = configurable
    else:
        try:
            nums = [int(n.strip()) for n in choice.split(",")]
            selected_indices = []
            for n in nums:
                idx = n - 1
                if idx in configurable:
                    selected_indices.append(idx)
                else:
                    console.print(f"[yellow]Skipping #{n} — already configured or invalid[/yellow]")
        except ValueError:
            console.print(
                "[red]Invalid input. Use 'all', 'none', or comma-separated numbers.[/red]"
            )
            return

    if not selected_indices:
        console.print("[dim]Nothing to configure.[/dim]")
        return

    # Execute setup for selected tools
    console.print()
    setup_fns = {
        "claude-code": _setup_claude_code,
        "claude-desktop": _setup_claude_desktop,
        "gemini": _setup_gemini,
        "cursor": _setup_cursor,
        "windsurf": _setup_windsurf,
        "cline": _setup_cline,
        "antigravity": _setup_antigravity,
        "codex": _setup_codex,
        "opencode": _setup_opencode,
    }

    success_count = 0
    for idx in selected_indices:
        client_id, info, _, _has_auto = detected[idx]
        fn = setup_fns.get(client_id)
        if fn and fn():
            success_count += 1

    console.print(f"\n[green]✓ Configured {success_count} tool(s)[/green]")
    if success_count > 0:
        console.print("[dim]Restart the configured tools to activate the MCP server.[/dim]")


def _prompt_numbered(prompt_text: str, options: list[tuple[str, str]], default: int = 1) -> str:
    """Show a numbered prompt and return the chosen option value.

    Args:
        prompt_text: Header text for the prompt.
        options: List of (value, label) tuples.
        default: 1-based default choice number.

    Returns:
        The value string of the chosen option.
    """
    console.print(f"{prompt_text}")
    for i, (_value, label) in enumerate(options, 1):
        marker = " [dim](default)[/dim]" if i == default else ""
        console.print(f"  [cyan]{i}[/cyan]) {label}{marker}")

    valid = [str(i) for i in range(1, len(options) + 1)]
    choice = Prompt.ask("Choose", choices=valid, default=str(default), show_choices=False)
    return options[int(choice) - 1][0]


def _setup_json() -> None:
    """Interactive flow to generate MCP JSON config for any tool."""
    console.print("[bold]Generate MCP JSON config[/bold]\n")
    console.print("This generates a JSON snippet you can paste into any tool's MCP config.\n")

    config_type = _prompt_numbered(
        "Config type:",
        [
            ("uvx", "uvx (no install required)"),
            ("regular", "Regular (uses installed binary)"),
        ],
    )

    use_full_path = False
    if config_type == "regular":
        path_choice = _prompt_numbered(
            "Command format:",
            [
                ("name", f"Command name ({MCP_SERVER_CMD})"),
                ("full", "Full path to binary"),
            ],
        )
        use_full_path = path_choice == "full"

    config_scope = _prompt_numbered(
        "Config scope:",
        [
            ("existing", "Add to existing config (server entry only)"),
            ("new", "New config file (includes mcpServers wrapper)"),
        ],
    )

    # Build the server entry
    if config_type == "uvx":
        server_entry = {
            "command": "uvx",
            "args": ["--from", "notebooklm-mcp-cli", "notebooklm-mcp"],
        }
    else:
        if use_full_path:
            binary_path = _find_mcp_server_path()
            if not binary_path:
                console.print(
                    "[yellow]Warning:[/yellow] notebooklm-mcp not found in PATH, "
                    "using command name instead"
                )
                binary_path = MCP_SERVER_CMD
            server_entry = {"command": binary_path}
        else:
            server_entry = {"command": MCP_SERVER_CMD}

    if config_scope == "new":
        output = {"mcpServers": {MCP_SERVER_NAME: server_entry}}
    else:
        output = {MCP_SERVER_NAME: server_entry}

    json_str = json.dumps(output, indent=2)

    console.print()
    console.print(Syntax(json_str, "json", theme="monokai", padding=1))
    console.print()

    if platform.system() == "Darwin" and Confirm.ask("Copy to clipboard?", default=True):
        try:
            subprocess.run(
                ["pbcopy"],
                input=json_str.encode(),
                check=True,
                timeout=5,
            )
            console.print("[green]✓[/green] Copied to clipboard")
        except (subprocess.SubprocessError, OSError):
            console.print("[yellow]Warning:[/yellow] Could not copy to clipboard")


# =============================================================================
# Commands
# =============================================================================


@app.command("add")
def setup_add(
    client: str = typer.Argument(
        ...,
        help="AI tool to configure, or 'all' to scan & configure interactively",
        shell_complete=_complete_client,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Claude Desktop profile: regular, 3p, or both",
    ),
) -> None:
    """
    Add Gemini Notebook MCP server to an AI tool.

    Configures the MCP server transport so the AI tool can access
    NotebookLM features (notebooks, sources, audio, research, etc).

    Examples:
        nlm setup add claude-code
        nlm setup add claude-desktop
        nlm setup add claude-desktop --profile 3p
        nlm setup add gemini
        nlm setup add github-copilot
        nlm setup add cursor
        nlm setup add windsurf
        nlm setup add cline
        nlm setup add antigravity
        nlm setup add opencode
        nlm setup add json
        nlm setup add all         # Interactive — detect and configure all
    """
    client = CLIENT_ALIASES.get(client, client)

    if client == "json":
        _setup_json()
        return

    if client == "all":
        if profile is not None:
            console.print("[red]Error:[/red] --profile is only valid for claude-desktop")
            raise typer.Exit(1)
        _setup_all()
        return

    if client not in CLIENT_REGISTRY:
        valid = ", ".join(list(CLIENT_REGISTRY.keys()) + ["json", "all"])
        console.print(f"[red]Error:[/red] Unknown client '{client}'")
        console.print(f"Available clients: {valid}")
        raise typer.Exit(1)

    if profile is not None and client != "claude-desktop":
        console.print("[red]Error:[/red] --profile is only valid for claude-desktop")
        raise typer.Exit(1)

    info = CLIENT_REGISTRY[client]
    console.print(f"\n[bold]{info['name']}[/bold] — Adding Gemini Notebook MCP\n")

    if not info["has_auto_setup"]:
        console.print(f"[yellow]Note:[/yellow] {info['name']} doesn't use MCP server config.")
        console.print(
            f"Use [cyan]nlm skill install {client}[/cyan] to install skill files instead."
        )
        raise typer.Exit(0)

    setup_fn = {
        "claude-code": _setup_claude_code,
        "claude-desktop": _setup_claude_desktop,
        "gemini": _setup_gemini,
        "github-copilot": _setup_github_copilot,
        "cursor": _setup_cursor,
        "windsurf": _setup_windsurf,
        "cline": _setup_cline,
        "antigravity": _setup_antigravity,
        "codex": _setup_codex,
        "opencode": _setup_opencode,
    }

    if client == "claude-desktop":
        success = _setup_claude_desktop(profile=profile)
    else:
        success = setup_fn[client]()
    if success:
        console.print(f"\n[dim]Restart {info['name']} to activate the MCP server.[/dim]")


@app.command("remove")
def setup_remove(
    client: str = typer.Argument(
        ...,
        help="AI tool to remove MCP from, or 'all' to remove from every configured tool",
        shell_complete=_complete_client,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Claude Desktop profile: regular, 3p, or both",
    ),
) -> None:
    """
    Remove Gemini Notebook MCP server from an AI tool.

    Examples:
        nlm setup remove gemini
        nlm setup remove claude-desktop --profile 3p
        nlm setup remove github-copilot
        nlm setup remove all
    """
    client = CLIENT_ALIASES.get(client, client)

    if client == "all":
        if profile is not None:
            console.print("[red]Error:[/red] --profile is only valid for claude-desktop")
            raise typer.Exit(1)
        _remove_all()
        return

    if client not in CLIENT_REGISTRY:
        valid = ", ".join(list(CLIENT_REGISTRY.keys()) + ["all"])
        console.print(f"[red]Error:[/red] Unknown client '{client}'")
        console.print(f"Available clients: {valid}")
        raise typer.Exit(1)

    if profile is not None and client != "claude-desktop":
        console.print("[red]Error:[/red] --profile is only valid for claude-desktop")
        raise typer.Exit(1)

    _remove_single(client, profile=profile)


def _remove_single(client: str, profile: str | None = None) -> bool:
    """Remove MCP from a single client. Returns True if removed."""
    if client == "claude-desktop":
        selected = _select_claude_desktop_profile_paths(profile, configured_only=True)
        if not selected:
            return False
        if not _ensure_claude_desktop_profiles_stopped(selected):
            return False

        removed_any = False
        for profile_name, config_path in selected.items():
            config = _read_json_config(config_path)
            servers = config.get("mcpServers", {})
            removed = _remove_mcp_entries(servers)

            if removed:
                config["mcpServers"] = servers
                _write_json_config(config_path, config)
                console.print(f"[green]✓[/green] Removed from Claude Desktop ({profile_name})")
                removed_any = True
            else:
                console.print(
                    f"[dim]Gemini Notebook MCP was not configured in Claude Desktop "
                    f"({profile_name}).[/dim]"
                )
        return removed_any

    # Client-specific removal via CLI (preferred)
    if client == "claude-code":
        claude_cmd = shutil.which("claude")
        if claude_cmd:
            try:
                result = subprocess.run(
                    [claude_cmd, "mcp", "remove", "-s", "user", MCP_SERVER_NAME],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                removed = result.returncode == 0
                last_error = result.stderr.strip()
                for legacy_name in LEGACY_MCP_SERVER_NAMES:
                    legacy_result = subprocess.run(
                        [claude_cmd, "mcp", "remove", "-s", "user", legacy_name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    removed = legacy_result.returncode == 0 or removed
                    if legacy_result.stderr.strip():
                        last_error = legacy_result.stderr.strip()
                if removed:
                    console.print("[green]✓[/green] Removed from Claude Code")
                    return True
                else:
                    console.print(f"[yellow]Note:[/yellow] {last_error}")
                    return False
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                console.print(f"[yellow]Warning:[/yellow] Could not run claude command: {e}")
                return False
        else:
            console.print("[yellow]Warning:[/yellow] 'claude' command not found")
            return False

    # CLI-based removal for Codex
    if client == "codex":
        codex_cmd = shutil.which("codex")
        if codex_cmd:
            try:
                result = subprocess.run(
                    [codex_cmd, "mcp", "remove", MCP_SERVER_NAME],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                removed = result.returncode == 0
                last_error = result.stderr.strip()
                for legacy_name in LEGACY_MCP_SERVER_NAMES:
                    legacy_result = subprocess.run(
                        [codex_cmd, "mcp", "remove", legacy_name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    removed = legacy_result.returncode == 0 or removed
                    if legacy_result.stderr.strip():
                        last_error = legacy_result.stderr.strip()
                if removed:
                    console.print("[green]✓[/green] Removed from Codex CLI")
                    return True
                else:
                    console.print(f"[yellow]Note:[/yellow] {last_error}")
                    return False
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
                console.print(f"[yellow]Warning:[/yellow] Could not run codex command: {e}")
                return False
        else:
            console.print("[yellow]Warning:[/yellow] 'codex' command not found")
            return False

    # OpenCode uses "mcp" key, not "mcpServers"
    if client == "opencode":
        config_path = _opencode_config_path()
        if not config_path.exists():
            console.print("[dim]No config file found for OpenCode.[/dim]")
            return False
        config = _read_json_config(config_path)
        mcp = config.get("mcp", {})
        removed = _remove_mcp_entries(mcp)
        if removed:
            config["mcp"] = mcp
            # Clean up experimental.mcp_timeout if no other MCP servers remain
            if not mcp:
                experimental = config.get("experimental", {})
                experimental.pop("mcp_timeout", None)
                if not experimental:
                    config.pop("experimental", None)
                else:
                    config["experimental"] = experimental
            _write_json_config(config_path, config)
            console.print("[green]✓[/green] Removed from OpenCode")
            return True
        else:
            console.print("[dim]Gemini Notebook MCP was not configured in OpenCode.[/dim]")
            return False

    # GitHub Copilot uses VS Code's ``servers`` key in .vscode/mcp.json
    if client == "github-copilot":
        config_path = _github_copilot_config_path()
        if not config_path.exists():
            console.print("[dim]No config file found for GitHub Copilot.[/dim]")
            return False
        config = _read_json_config(config_path)
        servers = config.get("servers", {})

        removed = _remove_mcp_entries(servers)

        if removed:
            config["servers"] = servers
            _write_json_config(config_path, config)
            console.print("[green]✓[/green] Removed from GitHub Copilot")
            return True

        console.print("[dim]Gemini Notebook MCP was not configured in GitHub Copilot.[/dim]")
        return False

    # JSON config-based clients
    config_paths = {
        "gemini": _gemini_config_path(),
        "cursor": _cursor_config_path(),
        "windsurf": _windsurf_config_path(),
        "cline": _cline_config_path(),
        "antigravity": _antigravity_config_path(),
    }

    config_path = config_paths.get(client)
    if not config_path or not config_path.exists():
        console.print(f"[dim]No config file found for {client}.[/dim]")
        return False

    config = _read_json_config(config_path)
    servers = config.get("mcpServers", {})

    removed = _remove_mcp_entries(servers)

    if removed:
        _write_json_config(config_path, config)
        console.print(f"[green]✓[/green] Removed from {CLIENT_REGISTRY[client]['name']}")
        return True
    else:
        console.print(
            f"[dim]Gemini Notebook MCP was not configured in {CLIENT_REGISTRY[client]['name']}.[/dim]"
        )
        return False


def _remove_all() -> None:
    """Remove MCP from all configured tools with explicit confirmation."""
    console.print("\n[bold]Scanning for configured tools...[/bold]\n")

    # Find all configured tools
    configured = []
    for client_id, info in CLIENT_REGISTRY.items():
        if not info["has_auto_setup"]:
            continue
        if _is_already_configured(client_id):
            configured.append((client_id, info))

    if not configured:
        console.print("[dim]No tools have Gemini Notebook MCP configured.[/dim]")
        return

    # Show what will be removed
    table = Table(title="Configured Tools")
    table.add_column("#", justify="right", style="cyan", width=3)
    table.add_column("Tool", style="bold")

    for i, (client_id, info) in enumerate(configured):  # noqa: B007
        table.add_row(str(i + 1), info["name"])

    console.print(table)

    # Strong warning and confirmation
    console.print()
    console.print(
        "[bold red]⚠  WARNING:[/bold red] This will remove the Gemini Notebook MCP server"
    )
    console.print(f"from [bold]{len(configured)}[/bold] tool(s) listed above.")
    console.print()

    if not Confirm.ask(
        "[bold]Are you sure you want to remove MCP from ALL configured tools?[/bold]",
        default=False,
    ):
        console.print("Cancelled.")
        return

    # Execute removal
    console.print()
    removed_count = 0
    for client_id, info in configured:  # noqa: B007
        if _remove_single(client_id):
            removed_count += 1

    console.print(f"\n[green]✓ Removed from {removed_count} tool(s)[/green]")
    if removed_count > 0:
        console.print("[dim]Restart the affected tools to apply changes.[/dim]")


@app.command("list")
def setup_list() -> None:
    """
    Show supported AI tools and their MCP configuration status.
    """
    table = Table(title="Gemini Notebook MCP Server Configuration")
    table.add_column("Client", style="cyan")
    table.add_column("Description")
    table.add_column("MCP Status", justify="center")
    table.add_column("Config Path", style="dim")

    for client_id, info in CLIENT_REGISTRY.items():
        status = "[dim]-[/dim]"
        config_path = ""

        if client_id == "claude-code":
            # Check via claude command
            claude_cmd = shutil.which("claude")
            if claude_cmd:
                try:
                    result = subprocess.run(
                        [claude_cmd, "mcp", "list"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if _cli_output_contains_mcp(result.stdout):
                        status = "[green]✓[/green]"
                except (subprocess.TimeoutExpired, OSError):
                    status = "[dim]?[/dim]"
                config_path = "claude mcp list"
            else:
                config_path = "not installed"

        elif client_id == "claude-desktop":
            profile_paths = _claude_desktop_profile_paths()
            if not profile_paths:
                table.add_row(
                    str(info["name"]),
                    str(info["description"]),
                    "[dim]-[/dim]",
                    "not installed",
                )
                continue

            profile_labels = {
                CLAUDE_DESKTOP_PROFILE_REGULAR: "regular",
                CLAUDE_DESKTOP_PROFILE_3P: "Relay AI / 3P",
            }
            for profile_name in CLAUDE_DESKTOP_PROFILES:
                path = profile_paths.get(profile_name)
                if path is None:
                    continue
                profile_status = "[dim]-[/dim]"
                if _is_configured(_read_json_config(path)):
                    profile_status = "[green]✓[/green]"
                display_path = str(path).replace(str(Path.home()), "~")
                table.add_row(
                    f"{info['name']} ({profile_labels[profile_name]})",
                    str(info["description"]),
                    profile_status,
                    display_path,
                )
            continue

        elif client_id == "gemini":
            path = _gemini_config_path()
            config = _read_json_config(path)
            if _is_configured(config):
                status = "[green]✓[/green]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "github-copilot":
            path = _github_copilot_config_path()
            config = _read_json_config(path)
            if _is_vscode_mcp_configured(config):
                status = "[green]✓[/green]"
            config_path = str(path)

        elif client_id == "cursor":
            path = _cursor_config_path()
            config = _read_json_config(path)
            if _is_configured(config):
                status = "[green]✓[/green]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "windsurf":
            path = _windsurf_config_path()
            config = _read_json_config(path)
            if _is_configured(config):
                status = "[green]✓[/green]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "cline":
            path = _cline_config_path()
            config = _read_json_config(path)
            if _is_configured(config):
                status = "[green]✓[/green]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "antigravity":
            path = _antigravity_config_path()
            config = _read_json_config(path)
            if _is_configured(config):
                status = "[green]✓[/green]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "codex":
            codex_cmd = shutil.which("codex")
            if codex_cmd:
                try:
                    result = subprocess.run(
                        [codex_cmd, "mcp", "list"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if _cli_output_contains_mcp(result.stdout):
                        status = "[green]✓[/green]"
                except (subprocess.TimeoutExpired, OSError):
                    status = "[dim]?[/dim]"
                config_path = "codex mcp list"
            else:
                config_path = "not installed"

        elif client_id == "opencode":
            path = _opencode_config_path()
            config = _read_json_config(path)
            mcp = config.get("mcp", {})
            if _configured_mcp_names(mcp):
                status = "[green]✓[/green]"
            config_path = str(path).replace(str(Path.home()), "~")

        table.add_row(str(info["name"]), str(info["description"]), status, config_path)

    console.print(table)
    console.print("\n[dim]Add MCP server:  nlm setup add <client>[/dim]")
    console.print("[dim]Install skills:  nlm skill install <tool>[/dim]")
