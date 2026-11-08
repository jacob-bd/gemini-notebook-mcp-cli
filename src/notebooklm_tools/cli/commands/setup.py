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

import questionary
import tomlkit
import typer
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table

from notebooklm_tools.cli.setup_safety import (
    ConfigParseError,
    atomic_write_text,
    backup_existing,
    read_json_config,
)
from notebooklm_tools.cli.utils import is_tool_on_system, make_console

console = make_console()

# Colored text instead of the default reverse-video highlight. prompt_toolkit's
# built-in style paints class:selected (checked rows) with `reverse`, which
# renders as a light block behind dark text. We override with explicit
# foreground colors + noreverse so pointed/checked rows read as colored text.
WIZARD_STYLE = questionary.Style(
    [
        ("qmark", "fg:#00afaf bold"),
        ("question", "bold"),
        ("answer", "fg:#00afaf bold"),
        ("pointer", "fg:#00afaf bold"),
        ("highlighted", "fg:#00afaf bold noreverse"),
        ("selected", "fg:#5faf5f noreverse"),
        ("separator", "fg:#808080"),
        ("instruction", "fg:#808080"),
        ("text", "noreverse"),
        ("disabled", "fg:#6c6c6c italic"),
    ]
)


def ask_with_back(question):
    """Run a questionary prompt with Esc bound to cancel (returns None), so
    callers can treat Esc as "go back". Esc is bound WITHOUT eager=True so
    prompt_toolkit's escape-timeout still lets arrow-key escape sequences
    through. Mocked questions (no .application) fall back to a plain .ask().

    Some prompts (e.g. confirm) carry read-only merged key bindings, so the Esc
    binding is merged in alongside them rather than added to them in place."""
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

    application = getattr(question, "application", None)
    if getattr(application, "key_bindings", None) is not None:
        back = KeyBindings()

        @back.add("escape")
        def _back(event):
            event.app.exit(result=None)

        application.key_bindings = merge_key_bindings([application.key_bindings, back])
        # prompt_toolkit waits ~1.5s by default to tell a lone Esc from an
        # arrow-key sequence; arrows arrive in a burst, so a short wait is enough.
        application.ttimeoutlen = 0.05
        application.timeoutlen = 0.05

    return question.ask()


app = typer.Typer(
    name="setup",
    help="Configure Gemini Notebook MCP server for AI tools",
    no_args_is_help=False,
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


def _default_server_command() -> str:
    """Full path to notebooklm-mcp when resolvable, else the bare command name.

    Desktop apps and some GUIs do not inherit the shell PATH, so the full path
    is the reliable default. Falls back to the bare name when detection fails.
    """
    return _find_mcp_server_path() or MCP_SERVER_CMD


def _read_json_config(path: Path) -> dict:
    """Read a JSON config file, returning empty dict if missing or blank.

    Raises:
        ConfigParseError: If the file exists but is malformed JSON or not an object.
    """
    return read_json_config(path)


def _write_json_config(path: Path, config: dict) -> Path | None:
    """Write a JSON config file atomically, creating a private backup if it exists."""
    backup = backup_existing(path, label="mcp-config")
    rendered = json.dumps(config, indent=2) + "\n"
    json.loads(rendered)  # validate serialization
    atomic_write_text(path, rendered)
    return backup


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


def _legacy_only_names(servers: object) -> list[str]:
    """Our entries that still use an old name, when none uses the current one."""
    names = _configured_mcp_names(servers)
    if MCP_SERVER_NAME in names:
        return []
    return [name for name in names if name in LEGACY_MCP_SERVER_NAMES]


# Shown in the wizard when a tool's entry still uses an old name.
OLD_NAME_REASON = "uses the old name"


def _old_name_reason(client_id: str) -> str | None:
    """Return OLD_NAME_REASON if the client's entry still uses a legacy name."""
    containers: list[tuple[dict, str]] = []
    try:
        if client_id == "claude-code":
            containers.append((_read_json_config(Path.home() / ".claude.json"), "mcpServers"))
        elif client_id == "claude-desktop":
            for path in _claude_desktop_profile_paths().values():
                containers.append((_read_json_config(path), "mcpServers"))
        elif client_id == "github-copilot":
            path = _github_copilot_config_path(scope="user")
            if path and path.exists():
                containers.append((_read_json_config(path), "servers"))
        elif client_id == "opencode":
            containers.append((_read_json_config(_opencode_config_path()), "mcp"))
        elif client_id == "codex":
            path = _codex_config_path() / "config.toml"
            if path.exists():
                containers.append((tomllib.loads(path.read_text(encoding="utf-8")), "mcp_servers"))
        else:
            path_fn = {
                "gemini": _gemini_config_path,
                "cursor": _cursor_config_path,
                "windsurf": _windsurf_config_path,
                "cline": _cline_config_path,
                "antigravity": _antigravity_config_path,
            }.get(client_id)
            if path_fn:
                containers.append((_read_json_config(path_fn()), "mcpServers"))
    except Exception:
        return None
    for config, key in containers:
        if _legacy_only_names(config.get(key, {})):
            return OLD_NAME_REASON
    return None


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
    entry = {"command": _default_server_command(), "args": []}
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
    entry = {"command": _default_server_command(), "args": []}
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
    """Get Codex CLI / ChatGPT desktop config directory path."""
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and codex_home.strip():
        return Path(codex_home.strip())
    return Path.home() / ".codex"


def _chatgpt_desktop_candidate_paths() -> list[Path]:
    """Return OS-specific candidate install paths for ChatGPT desktop app."""
    system = platform.system()
    if system == "Darwin":
        return [
            Path("/Applications/ChatGPT.app"),
            Path.home() / "Applications" / "ChatGPT.app",
        ]
    elif system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        candidates = []
        if local_app_data:
            candidates.append(Path(local_app_data) / "Programs" / "ChatGPT" / "ChatGPT.exe")
        return candidates
    else:
        return [
            Path("/opt/chatgpt"),
            Path.home() / ".local" / "share" / "applications" / "chatgpt.desktop",
            Path("/usr/share/applications") / "chatgpt.desktop",
        ]


def _detect_chatgpt_desktop() -> bool:
    """Check if ChatGPT desktop app is installed on this system."""
    for path in _chatgpt_desktop_candidate_paths():
        if path.exists():
            return True
    return platform.system() == "Linux" and bool(shutil.which("chatgpt"))


def _opencode_config_path() -> Path:
    """Get OpenCode global config path."""
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _github_copilot_config_path(scope: str = "project") -> Path | None:
    """Get GitHub Copilot workspace or user profile MCP config path."""
    if scope == "project":
        return Path(".vscode") / "mcp.json"
    elif scope == "user":
        system = platform.system()
        if system == "Darwin":
            return Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
        elif system == "Windows":
            appdata = os.environ.get("APPDATA")
            if not appdata:
                return None
            return Path(appdata) / "Code" / "User" / "mcp.json"
        else:
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
            return config_dir / "Code" / "User" / "mcp.json"
    return None


def _is_copilot_configured(scope: str = "project") -> bool:
    """Check if GitHub Copilot has Gemini Notebook MCP configured in the given scope."""
    config_path = _github_copilot_config_path(scope)
    if not config_path or not config_path.exists():
        return False
    try:
        config = _read_json_config(config_path)
        return _is_vscode_mcp_configured(config)
    except Exception:
        # Fallback for JSONC: check if file text contains MCP server name
        try:
            raw = config_path.read_text(encoding="utf-8")
            return any(name in raw for name in (MCP_SERVER_NAME, *LEGACY_MCP_SERVER_NAMES))
        except Exception:
            return False


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


_MSIX_PACKAGE_FAMILY_NAME = re.compile(r"^[a-z0-9.-]+_[a-z0-9]+$")


def _claude_desktop_msix_migrated_dir(package_dir: Path) -> Path | None:
    """Return the folder Claude Desktop moved its user data to, if any.

    Newer MSIX builds move user data from the package container to
    ``%LOCALAPPDATA%\\Claude-Data\\<package family name>`` and record the move
    with ``.user-data-<state>.<package family name>`` markers in the old
    package folder. A ``back`` marker means the data returned, so the old
    folder wins even when the new one exists.

    Unverified: when the new folder exists with neither a ``back`` nor a
    ``left`` marker, the app runs an extra check we have not read. We treat
    that case as migrated.
    """
    family_name = package_dir.name.lower()
    if not _MSIX_PACKAGE_FAMILY_NAME.match(family_name):
        return None

    legacy_dir = package_dir / "LocalCache" / "Roaming" / "Claude"
    if (legacy_dir / f".user-data-back.{family_name}").exists():
        return None

    # package_dir was located as <LOCALAPPDATA>/Packages/<family name>.
    migrated_dir = package_dir.parent.parent / "Claude-Data" / family_name
    return migrated_dir if migrated_dir.is_dir() else None


def _claude_desktop_msix_config_path() -> Path | None:
    """Find the config path used by a Claude Desktop MSIX installation."""
    package_dir = _claude_desktop_msix_package_dir()
    if package_dir is None:
        return None
    migrated_dir = _claude_desktop_msix_migrated_dir(package_dir)
    if migrated_dir is not None:
        return migrated_dir / "claude_desktop_config.json"
    return package_dir / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json"


def _windows_profile_dir_from_shell() -> Path | None:
    """Resolve the current Windows profile directory through the shell API."""
    try:
        import ctypes

        profile = ctypes.create_unicode_buffer(260)
        # CSIDL_PROFILE (40) resolves the current user's profile directory.
        result = ctypes.windll.shell32.SHGetFolderPathW(None, 40, None, 0, profile)
    except (AttributeError, OSError):
        return None
    if result == 0 and profile.value:
        return Path(profile.value)
    return None


def _windows_home_dir() -> Path:
    """Resolve the Windows home directory even when environment variables are absent."""
    try:
        return Path.home()
    except RuntimeError as exc:
        profile_dir = _windows_profile_dir_from_shell()
        if profile_dir is not None:
            return profile_dir
        raise RuntimeError("Could not determine Windows home directory.") from exc


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
        appdata = os.environ.get("APPDATA")
        local_app_data = os.environ.get("LOCALAPPDATA")
        home_dir = _windows_home_dir() if not appdata or not local_app_data else None

        regular_path = _claude_desktop_msix_config_path()
        if regular_path is None:
            if appdata:
                appdata_path = Path(appdata)
            else:
                assert home_dir is not None
                appdata_path = home_dir / "AppData" / "Roaming"
            regular_path = appdata_path / "Claude" / "claude_desktop_config.json"

        if local_app_data:
            local_app_data_path = Path(local_app_data)
        else:
            assert home_dir is not None
            local_app_data_path = home_dir / "AppData" / "Local"
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
                ["ps", "-axo", "pid=,ppid=,command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return ""
    if platform.system() == "Windows":
        return result.stdout
    return _without_own_process_ancestry(result.stdout, os.getpid())


def _without_own_process_ancestry(ps_output: str, own_pid: int) -> str:
    """Drop this process and its ancestors from a ``pid ppid command`` snapshot.

    Their command lines carry the client name (``nlm setup add claude-desktop``,
    or the shell that launched it) and would otherwise be mistaken for Claude
    Desktop itself. An ancestor whose executable *is* Claude Desktop is kept,
    since then Claude Desktop really is running.
    """
    parents: dict[int, int] = {}
    processes: list[tuple[int, str]] = []
    for line in ps_output.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        pid, ppid = int(parts[0]), int(parts[1])
        parents[pid] = ppid
        processes.append((pid, parts[2]))

    ancestry: set[int] = set()
    pid = own_pid
    while pid > 0 and pid not in ancestry:
        ancestry.add(pid)
        pid = parents.get(pid, 0)

    return "\n".join(
        command
        for pid, command in processes
        if pid not in ancestry or _is_claude_desktop_process_line(command.split()[0])
    )


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
    "chatgpt-desktop": "codex",
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
    config_path = Path.home() / ".claude.json"
    config = _read_json_config(config_path)
    servers = config.get("mcpServers", {})
    legacy = _legacy_only_names(servers)
    if legacy:
        return _rename_claude_code_entry(config_path, legacy[0], servers[legacy[0]])
    if _is_configured(config):
        console.print("[green]✓[/green] Already configured in Claude Code")
        return True

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print("[yellow]Warning:[/yellow] 'claude' command not found in PATH")
        console.print("  Install Claude Code: https://docs.anthropic.com/en/docs/claude-code")
        console.print()
        console.print("  Manual setup — add to [dim]~/.claude.json[/dim]:")
        console.print(
            f'    "mcpServers": {{ "{MCP_SERVER_NAME}": {{ "command": "{_default_server_command()}" }} }}'
        )
        return False

    try:
        backup_existing(config_path, label="claude-code-config")
        result = subprocess.run(
            [
                claude_cmd,
                "mcp",
                "add",
                "-s",
                "user",
                MCP_SERVER_NAME,
                "--",
                _default_server_command(),
            ],
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


def _rename_claude_code_entry(config_path: Path, old_name: str, entry: object) -> bool:
    """Rename a legacy Claude Code user entry, keeping its settings unchanged.

    Adds the entry under the current name first, then removes the old one, so a
    failed add leaves the working old entry in place.
    """
    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        console.print(
            f"[yellow]Warning:[/yellow] 'claude' command not found; can't rename "
            f"'{old_name}' to '{MCP_SERVER_NAME}' in Claude Code."
        )
        return False
    try:
        backup_existing(config_path, label="claude-code-config")
        added = subprocess.run(
            [claude_cmd, "mcp", "add-json", "-s", "user", MCP_SERVER_NAME, json.dumps(entry)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if added.returncode != 0 and "already exists" not in added.stderr.lower():
            console.print(
                f"[yellow]Warning:[/yellow] claude mcp add-json returned: {added.stderr.strip()}"
            )
            return False
        removed = subprocess.run(
            [claude_cmd, "mcp", "remove", "-s", "user", old_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        console.print(f"[yellow]Warning:[/yellow] Could not run claude command: {e}")
        return False

    # Trust the file, not the exit codes: confirm what actually changed.
    servers = _read_json_config(config_path).get("mcpServers", {})
    if MCP_SERVER_NAME not in servers:
        console.print(
            f"[yellow]Warning:[/yellow] Couldn't add '{MCP_SERVER_NAME}' to Claude Code; "
            f"'{old_name}' was left as it was. {added.stderr.strip()}"
        )
        return False
    if old_name in servers:
        console.print(
            f"[yellow]Warning:[/yellow] Added '{MCP_SERVER_NAME}' but couldn't remove the old "
            f"'{old_name}' entry. Remove it with: claude mcp remove {old_name} -s user "
            f"{removed.stderr.strip()}"
        )
        return True
    console.print(f"[green]✓[/green] Renamed in Claude Code: {old_name} → {MCP_SERVER_NAME}")
    return True


def _select_claude_desktop_profile_paths(
    profile: str | None = None, *, configured_only: bool = False
) -> dict[str, Path] | None:
    """Select Claude Desktop profiles for MCP setup or removal.

    Returns None (falsy, like "nothing selected") when the user presses Esc at
    the profile question, so callers can tell a deliberate skip from a failure.
    """
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
    selected = ask_with_back(
        questionary.select(
            "Multiple Claude Desktop profiles detected:",
            choices=[questionary.Choice(title=label, value=value) for value, label in options],
            instruction="(↑↓ move · Enter select · Esc to cancel)",
            style=WIZARD_STYLE,
        )
    )
    if selected is None:
        return None
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


def _setup_github_copilot(scope: str = "project") -> bool:
    """Add MCP to GitHub Copilot's workspace or user profile MCP config."""
    if scope not in ("project", "user"):
        console.print(f"[red]Error:[/red] Invalid scope '{scope}'. Must be 'project' or 'user'.")
        return False

    config_path = _github_copilot_config_path(scope)
    if config_path is None:
        console.print("[yellow]Warning:[/yellow] Could not locate VS Code user profile mcp.json.")
        return False

    if scope == "user":
        binary_path = _find_mcp_server_path()
        if not binary_path:
            console.print("[red]notebooklm-mcp is not installed in PATH[/red]")
            return False

        if (
            config_path.exists()
            and _is_copilot_configured(scope="user")
            and _old_name_reason("github-copilot") is None
        ):
            console.print("[green]✓[/green] Already configured in GitHub Copilot (user)")
            return True

        # A legacy entry is renamed in the JSON below; `code --add-mcp` would duplicate it.
        code_cmd = shutil.which("code") if _old_name_reason("github-copilot") is None else None
        if code_cmd:
            if config_path.exists():
                backup_existing(config_path, label="copilot-config")
            try:
                payload = json.dumps(
                    {
                        "name": MCP_SERVER_NAME,
                        "command": binary_path,
                        "args": [],
                    }
                )
                result = subprocess.run(
                    [code_cmd, "--add-mcp", payload],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    console.print("[green]✓[/green] Added to GitHub Copilot (user)")
                    console.print(f"  [dim]{config_path}[/dim]")
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass

        if config_path.exists():
            raw = config_path.read_text(encoding="utf-8")
            try:
                config = json.loads(raw)
            except json.JSONDecodeError:
                console.print(
                    f"[yellow]Note:[/yellow] {config_path} contains comments or custom formatting; "
                    "please configure via VS Code: 'code --add-mcp' or settings."
                )
                return False
        else:
            config = {}

        migrated = _migrate_legacy_mcp_entry(config, "servers")
        if _is_vscode_mcp_configured(config):
            if migrated:
                _write_json_config(config_path, config)
                console.print(
                    f"[green]✓[/green] Updated GitHub Copilot (user) to {MCP_SERVER_NAME}"
                )
            else:
                console.print("[green]✓[/green] Already configured in GitHub Copilot (user)")
            return True

        _add_vscode_mcp_server(config, extra={"command": binary_path})
        _write_json_config(config_path, config)
        console.print("[green]✓[/green] Added to GitHub Copilot (user)")
        console.print(f"  [dim]{config_path}[/dim]")
        return True

    # Project scope
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        try:
            config = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigParseError(config_path, exc) from exc
    else:
        config = {}

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


def _edit_codex_entry(
    path: Path, *, command: str | None = None, remove: bool = False
) -> Path | None:
    """Safely add or remove Gemini Notebook MCP entry in config.toml using tomlkit."""
    if not path.exists() and remove:
        return None

    raw_text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        doc = tomlkit.parse(raw_text)
    except Exception as exc:
        raise ConfigParseError(path, exc) from exc

    backup = backup_existing(path, label="codex-config")

    if remove:
        if "mcp_servers" in doc:
            servers = doc["mcp_servers"]
            for name in _configured_mcp_names(servers):
                del servers[name]
    else:
        if "mcp_servers" not in doc:
            doc["mcp_servers"] = tomlkit.table()
        servers = doc["mcp_servers"]
        renamed = None
        for legacy in LEGACY_MCP_SERVER_NAMES:
            if legacy in servers and _is_our_mcp_entry(legacy, servers[legacy]):
                old_entry = servers[legacy]
                del servers[legacy]
                # Keep the first legacy entry's own settings (e.g. enabled, env).
                if (
                    MCP_SERVER_NAME not in servers
                    and renamed is None
                    and isinstance(old_entry, dict)
                ):
                    renamed = old_entry
        if renamed is not None:
            servers[MCP_SERVER_NAME] = renamed

        entry = servers.get(MCP_SERVER_NAME)
        if entry is None or not isinstance(entry, dict):
            entry = tomlkit.table()
            servers[MCP_SERVER_NAME] = entry

        entry["command"] = command or _default_server_command()
        entry["args"] = []
        entry["tool_timeout_sec"] = 300

    atomic_write_text(path, tomlkit.dumps(doc))
    return backup


def _codex_repair_reason(path: Path | None = None) -> str | None:
    """Return a human-readable repair reason if Codex entry exists but is defective."""
    config_path = path or (_codex_config_path() / "config.toml")
    if not config_path.exists():
        return None
    try:
        doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    servers = doc.get("mcp_servers", {})
    if not isinstance(servers, dict):
        return None
    entry = None
    for name in MCP_SERVER_NAMES:
        if name in servers:
            entry = servers[name]
            break
    if entry is None or not isinstance(entry, dict):
        return None
    if _legacy_only_names(servers):
        return OLD_NAME_REASON

    cmd = entry.get("command", "")
    binary_path = _find_mcp_server_path()
    if binary_path and cmd == MCP_SERVER_CMD:
        return f"server command '{cmd}' is not an absolute path"
    timeout = entry.get("tool_timeout_sec")
    if timeout is None or (isinstance(timeout, (int, float)) and timeout < 300):
        return f"tool_timeout_sec ({timeout}) is below recommended 300"
    return None


def _setup_codex(repair: bool = False) -> bool:
    """Add MCP to Codex CLI and/or ChatGPT desktop app via codex CLI or direct TOML."""
    config_dir = _codex_config_path()
    config_path = config_dir / "config.toml"

    binary_path = _find_mcp_server_path()
    if not binary_path:
        console.print(
            "[red]Error:[/red] notebooklm-mcp was not found in PATH. "
            "Install it first or add its full path manually."
        )
        return False

    repair_reason = _codex_repair_reason(config_path)
    is_configured = False
    if config_path.exists():
        try:
            doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
            mcp = doc.get("mcp_servers", {})
            is_configured = bool(_configured_mcp_names(mcp))
        except Exception:
            pass

    if is_configured and not repair:
        console.print("[green]✓[/green] Already configured in Codex CLI / ChatGPT desktop")
        return True

    codex_cmd = shutil.which("codex")
    if codex_cmd and not is_configured:
        if config_path.exists():
            backup_existing(config_path, label="codex-config")
        try:
            result = subprocess.run(
                [codex_cmd, "mcp", "add", MCP_SERVER_NAME, "--", binary_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 and "already exists" not in result.stderr.lower():
                console.print(
                    f"[yellow]Warning:[/yellow] codex mcp add returned: {result.stderr.strip()}"
                )
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            console.print(f"[yellow]Warning:[/yellow] Could not run codex command: {e}")
            return False

    try:
        _edit_codex_entry(config_path, command=binary_path)
    except Exception as e:
        console.print(f"[red]Error updating Codex config.toml:[/red] {e}")
        return False

    if repair:
        console.print(
            f"[green]✓[/green] Repaired Codex / ChatGPT desktop configuration ({repair_reason})"
        )
    else:
        console.print("[green]✓[/green] Added to Codex CLI / ChatGPT desktop")
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
        "command": [_default_server_command()],
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
    if client_id == "codex":
        return _detect_chatgpt_desktop() or is_tool_on_system(
            binary="codex", root_dirs=[_codex_config_path()]
        )

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
            config = _read_json_config(Path.home() / ".claude.json")
            return _is_configured(config)

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
            toml_path = _codex_config_path() / "config.toml"
            if toml_path.exists():
                config = tomllib.loads(toml_path.read_text(encoding="utf-8"))
                return bool(_configured_mcp_names(config.get("mcp_servers", {})))
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


def build_json_snippet(
    config_type: str = "regular", use_full_path: bool = True, wrap: bool = True
) -> dict:
    """Build the MCP JSON snippet for pasting into another tool's config.

    Defaults to the full detected binary path in an ``mcpServers`` wrapper.
    """
    if config_type == "uvx":
        entry = {"command": "uvx", "args": ["--from", "notebooklm-mcp-cli", "notebooklm-mcp"]}
    else:
        entry = {"command": _default_server_command() if use_full_path else MCP_SERVER_CMD}
    return {"mcpServers": {MCP_SERVER_NAME: entry}} if wrap else {MCP_SERVER_NAME: entry}


def _render_and_copy_snippet(snippet: dict) -> None:
    """Print a snippet with syntax highlighting and copy it to the clipboard."""
    json_str = json.dumps(snippet, indent=2)
    console.print()
    console.print(Syntax(json_str, "json", theme="monokai", padding=1))
    console.print()

    from notebooklm_tools.cli.commands.setup_wizard import copy_to_clipboard

    if copy_to_clipboard(json_str):
        console.print("[green]✓[/green] Copied to clipboard")
    else:
        console.print("[dim]Copy it manually — no clipboard utility available.[/dim]")


def _note_if_path_undetected() -> None:
    """Warn when the full binary path can't be detected and the snippet is bare."""
    if _find_mcp_server_path() is None:
        console.print(
            "[dim]Note: couldn't find notebooklm-mcp on your PATH, so this uses the bare "
            "command. If your tool can't start it, replace it with the full path.[/dim]"
        )


def _setup_json() -> None:
    """Show the standard MCP snippet; offer advanced formats on request."""
    console.print("[bold]Copy MCP setup for a tool not listed[/bold]\n")
    console.print("Paste this into your tool's MCP settings:")
    _render_and_copy_snippet(build_json_snippet())
    _note_if_path_undetected()

    choice = ask_with_back(
        questionary.select(
            "Need a different format?",
            choices=["No, I'm done", "Advanced options"],
            style=WIZARD_STYLE,
        )
    )
    if choice is None or choice.startswith("No"):
        return

    style = ask_with_back(
        questionary.select(
            "Command style:",
            choices=["Installed binary (recommended)", "uvx (no install required)"],
            style=WIZARD_STYLE,
        )
    )
    if style is None:
        return
    config_type = "uvx" if "uvx" in style else "regular"

    use_full_path = True
    if config_type == "regular":
        path_choice = ask_with_back(
            questionary.select(
                "Path style:",
                choices=[
                    "Full path to the binary (most reliable)",
                    f"Just the command name ({MCP_SERVER_CMD})",
                ],
                style=WIZARD_STYLE,
            )
        )
        if path_choice is None:
            return
        use_full_path = path_choice.startswith("Full")

    scope_choice = ask_with_back(
        questionary.select(
            "Snippet shape:",
            choices=[
                "Full config file (with mcpServers wrapper)",
                "Server entry only (add to an existing config)",
            ],
            style=WIZARD_STYLE,
        )
    )
    if scope_choice is None:
        return
    wrap = scope_choice.startswith("Full")

    _render_and_copy_snippet(build_json_snippet(config_type, use_full_path, wrap))
    if config_type == "regular" and use_full_path:
        _note_if_path_undetected()


# =============================================================================
# Commands
# =============================================================================


@app.callback(invoke_without_command=True)
def setup_callback(ctx: typer.Context) -> None:
    """Configure Gemini Notebook MCP server for AI tools."""
    if ctx.invoked_subcommand is not None:
        return
    from notebooklm_tools.cli.commands.setup_wizard import run_setup_wizard

    raise typer.Exit(run_setup_wizard())


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
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="GitHub Copilot scope: user or project",
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
        try:
            _setup_all()
        except ConfigParseError as exc:
            console.print(
                f"[red]Error:[/red] Cannot parse {exc.path}; fix or remove it before adding MCP."
            )
            raise typer.Exit(1) from exc
        return

    if client not in CLIENT_REGISTRY:
        valid = ", ".join(list(CLIENT_REGISTRY.keys()) + ["json", "all"])
        console.print(f"[red]Error:[/red] Unknown client '{client}'")
        console.print(f"Available clients: {valid}")
        raise typer.Exit(1)

    if profile is not None and client != "claude-desktop":
        console.print("[red]Error:[/red] --profile is only valid for claude-desktop")
        raise typer.Exit(1)

    if scope is not None and client != "github-copilot":
        console.print("[red]Error:[/red] --scope is only valid for github-copilot")
        raise typer.Exit(1)

    if scope is not None and scope not in ("user", "project"):
        console.print("[red]Error:[/red] Invalid scope. Choose 'user' or 'project'.")
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
        "github-copilot": lambda: _setup_github_copilot(scope=scope or "project"),
        "cursor": _setup_cursor,
        "windsurf": _setup_windsurf,
        "cline": _setup_cline,
        "antigravity": _setup_antigravity,
        "codex": _setup_codex,
        "opencode": _setup_opencode,
    }

    try:
        if client == "claude-desktop":
            success = _setup_claude_desktop(profile=profile)
        else:
            success = setup_fn[client]()
    except ConfigParseError as exc:
        console.print(
            f"[red]Error:[/red] Cannot parse {exc.path}; fix or remove it before adding MCP."
        )
        raise typer.Exit(1) from exc
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
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="GitHub Copilot scope: user or project",
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
        try:
            _remove_all()
        except ConfigParseError as exc:
            console.print(
                f"[red]Error:[/red] Cannot parse {exc.path}; fix or remove it before removing MCP."
            )
            raise typer.Exit(1) from exc
        return

    if client not in CLIENT_REGISTRY:
        valid = ", ".join(list(CLIENT_REGISTRY.keys()) + ["all"])
        console.print(f"[red]Error:[/red] Unknown client '{client}'")
        console.print(f"Available clients: {valid}")
        raise typer.Exit(1)

    if profile is not None and client != "claude-desktop":
        console.print("[red]Error:[/red] --profile is only valid for claude-desktop")
        raise typer.Exit(1)

    if scope is not None and client != "github-copilot":
        console.print("[red]Error:[/red] --scope is only valid for github-copilot")
        raise typer.Exit(1)

    if scope is not None and scope not in ("user", "project"):
        console.print("[red]Error:[/red] Invalid scope. Choose 'user' or 'project'.")
        raise typer.Exit(1)

    try:
        _remove_single(client, profile=profile, scope=scope or "project")
    except ConfigParseError as exc:
        console.print(
            f"[red]Error:[/red] Cannot parse {exc.path}; fix or remove it before removing MCP."
        )
        raise typer.Exit(1) from exc


def _remove_single(client: str, profile: str | None = None, scope: str = "project") -> bool:
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
        config_path = Path.home() / ".claude.json"
        config = _read_json_config(config_path)
        names = _configured_mcp_names(config.get("mcpServers", {}))
        if not names:
            console.print("[dim]Gemini Notebook MCP was not configured in Claude Code.[/dim]")
            return False

        claude_cmd = shutil.which("claude")
        if claude_cmd:
            try:
                backup_existing(config_path, label="claude-code-config")
                removed = False
                last_error = ""
                for name in names:
                    result = subprocess.run(
                        [claude_cmd, "mcp", "remove", "-s", "user", name],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    removed = result.returncode == 0 or removed
                    if result.stderr.strip():
                        last_error = result.stderr.strip()
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
            _remove_mcp_entries(config["mcpServers"])
            _write_json_config(config_path, config)
            console.print("[green]✓[/green] Removed from Claude Code configuration")
            return True

    # Removal for Codex CLI / ChatGPT desktop
    if client == "codex":
        config_path = _codex_config_path() / "config.toml"
        if not config_path.exists():
            console.print(
                "[dim]Gemini Notebook MCP was not configured in Codex / ChatGPT desktop.[/dim]"
            )
            return False
        try:
            config = tomlkit.parse(config_path.read_text(encoding="utf-8"))
            if not _configured_mcp_names(config.get("mcp_servers", {})):
                console.print(
                    "[dim]Gemini Notebook MCP was not configured in Codex / ChatGPT desktop.[/dim]"
                )
                return False
            _edit_codex_entry(config_path, remove=True)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Could not remove Codex MCP entry:[/red] {exc}")
            return False
        console.print("[green]✓[/green] Removed from Codex CLI / ChatGPT desktop")
        return True

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

    # GitHub Copilot uses VS Code's ``servers`` key
    if client == "github-copilot":
        config_path = _github_copilot_config_path(scope=scope)
        if not config_path or not config_path.exists():
            console.print(f"[dim]No config file found for GitHub Copilot ({scope}).[/dim]")
            return False

        raw = config_path.read_text(encoding="utf-8")
        try:
            config = json.loads(raw)
        except json.JSONDecodeError:
            console.print(
                f"[yellow]Note:[/yellow] {config_path} contains comments or custom formatting; "
                "cannot safely modify without losing comments."
            )
            console.print(f"Please remove '{MCP_SERVER_NAME}' manually from: {config_path}")
            return False

        servers = config.get("servers", {})
        removed = _remove_mcp_entries(servers)

        if removed:
            config["servers"] = servers
            _write_json_config(config_path, config)
            console.print(f"[green]✓[/green] Removed from GitHub Copilot ({scope})")
            return True

        console.print(
            f"[dim]Gemini Notebook MCP was not configured in GitHub Copilot ({scope}).[/dim]"
        )
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
            path = Path.home() / ".claude.json"
            try:
                if _is_configured(_read_json_config(path)):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

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
                try:
                    if _is_configured(_read_json_config(path)):
                        profile_status = "[green]✓[/green]"
                except (OSError, ConfigParseError):
                    profile_status = "[dim]?[/dim]"
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
            try:
                config = _read_json_config(path)
                if _is_configured(config):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "github-copilot":
            found = False
            for scope, label in (("user", "user profile"), ("project", "workspace")):
                path = _github_copilot_config_path(scope)
                if path is None:
                    continue
                try:
                    configured = _is_copilot_configured(scope)
                except (OSError, ConfigParseError):
                    configured = False
                if configured:
                    table.add_row(
                        f"{info['name']} ({label})",
                        str(info["description"]),
                        "[green]✓[/green]",
                        str(path).replace(str(Path.home()), "~"),
                    )
                    found = True
            if not found:
                user_path = _github_copilot_config_path("user")
                table.add_row(
                    str(info["name"]),
                    str(info["description"]),
                    "[dim]-[/dim]",
                    str(user_path).replace(str(Path.home()), "~")
                    if user_path
                    else "user profile unavailable",
                )
            continue

        elif client_id == "cursor":
            path = _cursor_config_path()
            try:
                config = _read_json_config(path)
                if _is_configured(config):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "windsurf":
            path = _windsurf_config_path()
            try:
                config = _read_json_config(path)
                if _is_configured(config):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "cline":
            path = _cline_config_path()
            try:
                config = _read_json_config(path)
                if _is_configured(config):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "antigravity":
            path = _antigravity_config_path()
            try:
                config = _read_json_config(path)
                if _is_configured(config):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "codex":
            path = _codex_config_path() / "config.toml"
            try:
                if path.exists():
                    config = tomllib.loads(path.read_text(encoding="utf-8"))
                    if _configured_mcp_names(config.get("mcp_servers", {})):
                        status = "[green]✓[/green]"
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        elif client_id == "opencode":
            path = _opencode_config_path()
            try:
                config = _read_json_config(path)
                mcp = config.get("mcp", {})
                if _configured_mcp_names(mcp):
                    status = "[green]✓[/green]"
            except (OSError, ConfigParseError):
                status = "[dim]?[/dim]"
            config_path = str(path).replace(str(Path.home()), "~")

        table.add_row(str(info["name"]), str(info["description"]), status, config_path)

    console.print(table)
    console.print("\n[dim]Add MCP server:  nlm setup add <client>[/dim]")
    console.print("[dim]Install skills:  nlm skill install <tool>[/dim]")
