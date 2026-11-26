"""Durable, fail-closed at-most-once guard for automatic research imports.

A claim is created *before* a provider mutation. A missing confirmation is
never an invitation to replay the mutation, including after a process restart.
This protects one shared local storage root; it cannot deduplicate external
clients, explicit manual imports, or other installations.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from notebooklm_tools.utils.config import get_config, get_storage_dir


def _claim_path(client: object, notebook_id: str, task_id: str) -> Path:
    """Partition claims by configured account profile, notebook and task."""
    profile = getattr(client, "_profile_name", None)
    if not isinstance(profile, str) or not profile.strip():
        # Environment-only credentials lack a stable, trusted profile binding.
        if getattr(client, "_is_env_auth", False) is True:
            raise ValueError("Automatic import needs a stable auth profile")
        profile = get_config().auth.default_profile
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError("Automatic import profile is not identifiable")
    if not all(isinstance(v, str) and v.strip() for v in (notebook_id, task_id)):
        raise ValueError("Notebook ID and task ID must be nonempty strings")

    root = get_storage_dir() / "research-auto-import-claims"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Unsafe automatic import claim directory")
    identity = json.dumps([profile, notebook_id, task_id], separators=(",", ":"))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return root / (digest + ".json")


def _confirmed(path: Path) -> bool:
    """Corrupt, missing, and in-flight receipts are all unconfirmed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(data, dict) and data.get("state") == "confirmed"
    except (OSError, UnicodeError, ValueError, TypeError):
        return False


def _mark_confirmed(path: Path) -> None:
    """Atomically publish successful provider confirmation with disk flush."""
    fd, tmp = tempfile.mkstemp(prefix=".confirmed-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"state": "confirmed", "timestamp": int(time.time())}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def import_once(
    client: object, notebook_id: str, task_id: str, import_callback: Callable[[], Any]
) -> tuple[bool | None, str, str | None]:
    """Return (imported, import_state, safe_error_code).

    A confirmed claim can be read repeatedly. An unconfirmed claim is NEVER
    replayed; the operator must reconcile sources before any manual retry.
    """
    try:
        path = _claim_path(client, notebook_id, task_id)
    except (OSError, ValueError, TypeError):
        return None, "guard_unavailable", "import_guard_unavailable"

    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if _confirmed(path):
            return True, "confirmed", None
        return None, "unconfirmed", "import_unconfirmed"
    except OSError:
        return None, "guard_unavailable", "import_guard_unavailable"

    # Existing path, even with an incomplete body, blocks another send.
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"state": "pending", "timestamp": int(time.time())}, handle)
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, ValueError, TypeError):
        return None, "unconfirmed", "import_unconfirmed"

    try:
        import_callback()
    except Exception:
        return None, "unconfirmed", "import_unconfirmed"

    try:
        _mark_confirmed(path)
    except OSError:
        return None, "unconfirmed", "import_unconfirmed"
    return True, "confirmed", None
