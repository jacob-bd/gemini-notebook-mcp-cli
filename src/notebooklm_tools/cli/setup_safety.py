"""Safe configuration file reading, atomic writing, and backup primitives."""

import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path


class ConfigParseError(ValueError):
    """Raised when a configuration file exists but cannot be parsed."""

    def __init__(self, path: Path, cause: Exception):
        super().__init__(f"Cannot parse {path}: {cause}")
        self.path = path
        self.cause = cause


_backup_log: ContextVar[list[Path] | None] = ContextVar("nlm_setup_backups", default=None)


@contextmanager
def capture_backups() -> Iterator[list[Path]]:
    """Context manager to record all backups created during an operation."""
    recorded: list[Path] = []
    token = _backup_log.set(recorded)
    try:
        yield recorded
    finally:
        _backup_log.reset(token)


def read_json_config(path: Path) -> dict:
    """Read a JSON config file, returning empty dict if missing or blank.

    Raises:
        ConfigParseError: If file exists but is malformed or not a JSON object.
    """
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigParseError(path, exc) from exc
    if not isinstance(value, dict):
        raise ConfigParseError(path, ValueError("expected a JSON object"))
    return value


def backup_existing(path: Path, *, label: str) -> Path | None:
    """Create a private dated backup of an existing file or directory.

    Args:
        path: File or directory to back up.
        label: Descriptive tag for the backup filename.

    Returns:
        The Path to the created backup, or None if path does not exist.

    Raises:
        ValueError: If path or backup root is a symlink.
        OSError: If copying or permission setting fails.
    """
    if path.is_symlink():
        raise ValueError(f"Refusing symbolic link: {path}")
    if not path.exists():
        return None

    # Same storage root as the rest of the app (honors NOTEBOOKLM_MCP_CLI_PATH).
    from notebooklm_tools.utils.config import get_storage_dir

    root = get_storage_dir() / "backups"
    if root.is_symlink():
        raise ValueError(f"Refusing symbolic-link backup root: {root}")

    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    root.chmod(0o700)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = root / f"{stamp}-{uuid.uuid4().hex[:8]}-{label}"

    try:
        if path.is_dir():
            shutil.copytree(path, backup_path, symlinks=True)
            descendants = [backup_path, *backup_path.rglob("*")]
        else:
            shutil.copy2(path, backup_path)
            descendants = [backup_path]

        for item in descendants:
            if item.is_symlink():
                continue
            mode = 0o700 if item.is_dir() or (item.stat().st_mode & stat.S_IXUSR) else 0o600
            item.chmod(mode)
    except Exception:
        if backup_path.exists():
            if backup_path.is_dir():
                shutil.rmtree(backup_path, ignore_errors=True)
            else:
                backup_path.unlink(missing_ok=True)
        raise

    log = _backup_log.get()
    if log is not None:
        log.append(backup_path)

    return backup_path


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write text to path via a closed temporary file in the same directory.

    Preserves original file permissions if file already exists.

    Raises:
        ValueError: If path is a symbolic link.
    """
    if path.is_symlink():
        raise ValueError(f"Refusing symbolic link: {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path_str = tempfile.mkstemp(dir=path.parent, prefix=".tmp-nlm-")
    temp_path = Path(temp_path_str)

    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        if path.exists():
            temp_path.chmod(path.stat().st_mode & 0o777)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
