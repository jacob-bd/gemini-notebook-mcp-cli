"""Configuration management for NotebookLM MCP CLI.

Uses ~/.notebooklm-mcp-cli/ for all data (config, profiles, Chrome profile).
Supports automatic migration from old locations:
- ~/.notebooklm-mcp/ (old MCP-only location, pre-0.2.13)
- ~/.nlm/ (old CLI location)
"""

import os
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Storage Location
# =============================================================================

STORAGE_DIR_NAME = ".notebooklm-mcp-cli"


def safe_mkdir(
    path: Path, *, parents: bool = False, exist_ok: bool = True, mode: int = 0o777
) -> None:
    """Create a directory, working around Python 3.14 Windows regression.

    On Python 3.14 + Windows, ``pathlib.mkdir(parents=True, exist_ok=True)``
    can raise ``FileExistsError`` (WinError 183) even when the directory
    already exists.  This wrapper catches that specific failure.
    See: https://github.com/jacob-bd/notebooklm-mcp-cli/issues/169
    """
    try:
        path.mkdir(parents=parents, exist_ok=exist_ok, mode=mode)
    except FileExistsError:
        if path.is_dir():
            return
        raise
    except PermissionError:
        raise PermissionError(
            f"Cannot write to {path} — permission denied.\n"
            f'On Windows, fix with: icacls "{path.parent}" /grant %USERNAME%:(OI)(CI)F /t'
        ) from None


_ALLOWED_BASE_HOSTS = {
    "notebooklm.google.com",
    "notebooklm.cloud.google.com",
}


def get_base_url() -> str:
    """Get the NotebookLM base URL.

    Defaults to the personal URL (https://notebooklm.google.com).
    Set NOTEBOOKLM_BASE_URL to override, e.g. for enterprise:
        export NOTEBOOKLM_BASE_URL=https://notebooklm.cloud.google.com
    """
    url = os.environ.get("NOTEBOOKLM_BASE_URL", "https://notebooklm.google.com").rstrip("/")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_BASE_HOSTS:
        raise ValueError(
            f"NOTEBOOKLM_BASE_URL must use https and one of: {_ALLOWED_BASE_HOSTS}. Got: {url}"
        )
    return url


def get_default_language() -> str:
    """Get default language from NOTEBOOKLM_HL env var, falling back to 'en'.

    Mirrors NotebookLM web behavior: when creating artifacts, the notebook's
    interface language (hl) is used as the default, so users don't need to
    specify --language on every command.
    """
    return os.environ.get("NOTEBOOKLM_HL", "en")


def get_storage_dir() -> Path:
    """Get the main storage directory (~/.notebooklm-mcp-cli/).

    Returns the path, creating it if needed.
    """
    if env_path := os.environ.get("NOTEBOOKLM_MCP_CLI_PATH"):
        storage_dir = Path(env_path)
    else:
        storage_dir = Path.home() / STORAGE_DIR_NAME

    safe_mkdir(storage_dir, mode=0o700)
    return storage_dir


def get_config_dir() -> Path:
    """Get the configuration directory path (alias for get_storage_dir)."""
    return get_storage_dir()


def get_data_dir() -> Path:
    """Get the data directory path (alias for get_storage_dir)."""
    return get_storage_dir()


def get_profiles_dir() -> Path:
    """Get the profiles directory path."""
    profiles_dir = get_storage_dir() / "profiles"
    safe_mkdir(profiles_dir)
    return profiles_dir


def get_profile_dir(profile_name: str = "default") -> Path:
    """Get directory for a specific profile."""
    profile_dir = get_profiles_dir() / profile_name
    safe_mkdir(profile_dir, parents=True)
    return profile_dir


def get_chrome_profile_dir(profile_name: str = "default") -> Path:
    """Get Chrome profile directory for automated auth.

    Each NLM profile gets its own Chrome user-data-dir so different
    Google accounts can be used for different profiles.

    ``NOTEBOOKLM_CHROME_PROFILE_DIR`` overrides this with a fixed,
    already-authenticated Chrome user-data-dir (e.g. one you set up and
    logged into NotebookLM by hand), instead of the tool's self-managed
    profile directory.

    For backward compatibility, the "default" profile uses the old
    chrome-profile/ directory if it exists, keeping single-profile
    users' experience unchanged.
    """
    if env_dir := os.environ.get("NOTEBOOKLM_CHROME_PROFILE_DIR"):
        chrome_dir = Path(env_dir)
        safe_mkdir(chrome_dir, parents=True)
        return chrome_dir

    storage = get_storage_dir()

    # Backward compatibility: use old location for default profile if it exists
    if profile_name == "default":
        old_chrome_dir = storage / "chrome-profile"
        if old_chrome_dir.exists():
            return old_chrome_dir

    # New multi-profile structure
    chrome_dir = storage / "chrome-profiles" / profile_name
    safe_mkdir(chrome_dir, parents=True)
    return chrome_dir


def get_snap_chrome_profile_dir(
    profile_name: str = "default",
    snap_common: Path | None = None,
) -> Path:
    """Get a snap-accessible Chrome profile directory.

    Snap packages (like snap Chromium) are confined by AppArmor and can
    only write to ~/snap/<snap-name>/common/. This function returns a
    profile directory inside that accessible location.

    Args:
        profile_name: NLM profile name
        snap_common: Path to snap common directory (e.g., ~/snap/chromium/common)
                     If None, auto-detects from installed snaps.

    Returns:
        Path to a snap-accessible Chrome profile directory.
    """
    if snap_common is None:
        # Auto-detect snap common directory
        for snap_name in ("chromium", "google-chrome"):
            candidate = Path.home() / "snap" / snap_name / "common"
            if candidate.exists():
                snap_common = candidate
                break

    if snap_common is None:
        # Fallback: use chromium common dir (create if needed)
        snap_common = Path.home() / "snap" / "chromium" / "common"
        safe_mkdir(snap_common, parents=True)

    chrome_dir = snap_common / "notebooklm-mcp-cli" / "chrome-profiles" / profile_name
    safe_mkdir(chrome_dir, parents=True)
    return chrome_dir


def get_firefox_profile_dir(profile_name: str = "default") -> Path:
    """Get Firefox profile directory kept for backwards compatibility."""
    firefox_dir = get_storage_dir() / "firefox-profiles" / profile_name
    safe_mkdir(firefox_dir, parents=True)
    return firefox_dir


def get_config_file() -> Path:
    """Get the config file path."""
    return get_storage_dir() / "config.toml"


def get_auth_cache_file() -> Path:
    """Get the auth cache file path (for MCP compatibility)."""
    return get_storage_dir() / "auth.json"


# =============================================================================
# Migration Support
# =============================================================================

# Old locations for Chrome profiles (checked for migration)
OLD_CHROME_PROFILES = [
    Path.home() / ".notebooklm-mcp" / "chrome-profile",  # Old MCP (pre-0.2.13)
    Path.home() / ".nlm" / "chrome-profile",  # Old CLI
]

# Old locations for auth.json (checked for migration)
OLD_AUTH_LOCATIONS = [
    Path.home() / ".notebooklm-mcp" / "auth.json",  # Old MCP (pre-0.2.13)
]

# Old locations for aliases
OLD_ALIAS_LOCATIONS: list[Path] = []

# Try to add old CLI alias location (platformdirs-based)
try:
    from platformdirs import user_config_dir

    OLD_ALIAS_LOCATIONS.append(Path(user_config_dir("nlm")) / "aliases.json")
except ImportError:
    pass


def check_migration_sources() -> dict[str, list[Path]]:
    """Check for existing data that can be migrated.

    Returns dict with:
        - chrome_profiles: list of existing Chrome profile directories
        - auth_files: list of existing auth.json files
        - aliases: list of existing alias files
    """
    result = {
        "chrome_profiles": [],
        "auth_files": [],
        "aliases": [],
    }

    for profile_path in OLD_CHROME_PROFILES:
        if profile_path.exists() and profile_path.is_dir():
            result["chrome_profiles"].append(profile_path)

    for auth_path in OLD_AUTH_LOCATIONS:
        if auth_path.exists() and auth_path.is_file():
            result["auth_files"].append(auth_path)

    for alias_path in OLD_ALIAS_LOCATIONS:
        if alias_path.exists() and alias_path.is_file():
            result["aliases"].append(alias_path)

    return result


def migrate_auth_file(source_path: Path, dry_run: bool = True) -> str | None:
    """Migrate auth.json from old location.

    Args:
        source_path: Path to the old auth.json file
        dry_run: If True, only report what would be done

    Returns:
        Action description if migration was done, None if skipped
    """
    new_auth = get_storage_dir() / "auth.json"

    if new_auth.exists():
        return None  # Already have auth, don't overwrite

    action = f"Copy auth tokens from {source_path}"
    if not dry_run:
        shutil.copy2(source_path, new_auth)

    return action


def migrate_aliases(source_path: Path, dry_run: bool = True) -> str | None:
    """Migrate aliases from old location.

    Args:
        source_path: Path to the old aliases.json file
        dry_run: If True, only report what would be done

    Returns:
        Action description if migration was done, None if skipped
    """
    new_aliases = get_storage_dir() / "aliases.json"

    if new_aliases.exists():
        return None  # Already have aliases, don't overwrite

    action = f"Copy aliases from {source_path}"
    if not dry_run:
        shutil.copy2(source_path, new_aliases)

    return action


def migrate_chrome_profile(source_path: Path, dry_run: bool = True) -> str | None:
    """Migrate Chrome profile from old location.

    Note: Chrome profile copy provides one-click login experience.
    User will see account chooser but won't need to enter password.

    Args:
        source_path: Path to the old chrome-profile directory
        dry_run: If True, only report what would be done

    Returns:
        Action description if migration was done, None if skipped
    """
    new_chrome = get_storage_dir() / "chrome-profile"

    if new_chrome.exists():
        return None  # Already have a Chrome profile, don't overwrite

    action = f"Copy Chrome profile from {source_path}"
    if not dry_run:
        shutil.copytree(source_path, new_chrome)

    return action


def run_migration(dry_run: bool = True, prefer_source: str | None = None) -> list[str]:
    """Run migration from old locations.

    Args:
        dry_run: If True, only report what would be done
        prefer_source: If multiple Chrome profiles exist, prefer "cli" or "mcp"

    Returns:
        List of actions taken (or that would be taken)
    """
    actions = []
    sources = check_migration_sources()

    # Migrate auth.json (first one found wins)
    for auth_path in sources["auth_files"]:
        action = migrate_auth_file(auth_path, dry_run)
        if action:
            actions.append(action)
            break  # Only migrate once

    # Migrate aliases (first one found wins)
    for alias_path in sources["aliases"]:
        action = migrate_aliases(alias_path, dry_run)
        if action:
            actions.append(action)
            break  # Only migrate once

    # Migrate Chrome profile
    if sources["chrome_profiles"]:
        # If user has preference, try that first
        if prefer_source == "cli":
            # Prefer CLI location
            sources["chrome_profiles"].sort(key=lambda p: 0 if ".nlm" in str(p) else 1)
        elif prefer_source == "mcp":
            # Prefer MCP location
            sources["chrome_profiles"].sort(key=lambda p: 0 if ".notebooklm-mcp" in str(p) else 1)

        # Use the first available
        for profile_path in sources["chrome_profiles"]:
            action = migrate_chrome_profile(profile_path, dry_run)
            if action:
                actions.append(action)
                break  # Only migrate once

    return actions


def auto_migrate_if_needed() -> list[str]:
    """Automatically migrate data from old locations if new location is empty.

    This is called automatically when accessing storage to ensure seamless
    upgrade experience. Users don't need to do anything manually.

    Returns:
        List of migration actions performed (empty if nothing migrated)
    """
    storage = get_storage_dir()

    # Check if new location already has data
    has_auth = (storage / "auth.json").exists()
    has_chrome = (storage / "chrome-profile").exists() or (storage / "chrome-profiles").exists()

    # If we already have data, no migration needed
    if has_auth and has_chrome:
        return []

    # Run migration (not dry run)
    return run_migration(dry_run=False)


# =============================================================================
# Configuration Models
# =============================================================================


class OutputConfig(BaseModel):
    """Output formatting configuration."""

    format: str = Field(default="table", description="Default output format: table, json, compact")
    color: bool = Field(default=True, description="Enable colored output")
    short_ids: bool = Field(default=True, description="Show abbreviated IDs by default")


class AuthConfig(BaseModel):
    """Authentication configuration."""

    browser: str = Field(
        default="auto",
        description=("Browser for auth: auto, chrome, arc, brave, edge, chromium, vivaldi, opera"),
    )
    default_profile: str = Field(default="default", description="Default profile name")


class Config(BaseModel):
    """Main configuration model."""

    output: OutputConfig = Field(default_factory=OutputConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)


def load_config() -> Config:
    """Load configuration from file and environment."""
    config_file = get_config_file()
    config_data: dict[str, Any] = {}

    # Load from file if exists
    if config_file.exists():
        try:
            import tomllib

            with open(config_file, "rb") as f:
                config_data = tomllib.load(f)
        except Exception:
            pass  # Use defaults on error

    # Apply environment overrides
    if output_format := os.environ.get("NLM_OUTPUT_FORMAT"):
        config_data.setdefault("output", {})["format"] = output_format

    if os.environ.get("NLM_NO_COLOR"):
        config_data.setdefault("output", {})["color"] = False

    if browser := os.environ.get("NLM_BROWSER"):
        config_data.setdefault("auth", {})["browser"] = browser

    if profile := os.environ.get("NLM_PROFILE"):
        config_data.setdefault("auth", {})["default_profile"] = profile

    return Config(**config_data)


def save_config(config: Config) -> None:
    """Save configuration to file."""
    config_file = get_config_file()
    safe_mkdir(config_file.parent, parents=True)

    # Convert to TOML format
    toml_content = _config_to_toml(config)
    config_file.write_text(toml_content, encoding="utf-8")


def _config_to_toml(config: Config) -> str:
    """Convert config model to TOML string."""
    lines = []

    lines.append("[output]")
    lines.append(f'format = "{config.output.format}"')
    lines.append(f"color = {'true' if config.output.color else 'false'}")
    lines.append(f"short_ids = {'true' if config.output.short_ids else 'false'}")
    lines.append("")

    lines.append("[auth]")
    lines.append(f'browser = "{config.auth.browser}"')
    lines.append(f'default_profile = "{config.auth.default_profile}"')
    lines.append("")

    return "\n".join(lines)


# Global config instance (lazy loaded)
_config: Config | None = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Reset the global configuration (for testing)."""
    global _config
    _config = None
