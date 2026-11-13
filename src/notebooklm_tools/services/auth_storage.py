"""Storage mode service.

Orchestrates storage mode inspection, switching, conflict resolution, and root relocation.
Translates core storage contracts into service results and errors.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any, TypedDict

from notebooklm_tools.services.errors import ServiceError, ValidationError
from notebooklm_tools.utils.config import (
    get_config,
    get_profile_dir,
    get_storage_dir,
    set_auth_storage_mode,
    validate_profile_name,
)


class StorageStatusResult(TypedDict, total=False):
    """Result of querying storage status for a profile."""

    profile: str
    mode: str
    has_marker: bool
    has_ciphertext: bool
    has_legacy: bool
    protected_residue: bool
    has_conflict: bool
    conflict_details: str | None
    has_pending_op: bool
    pending_op_details: str | None


class StorageSetResult(TypedDict):
    """Result of setting storage mode for a profile."""

    profile: str
    mode: str
    status: str
    message: str


def get_storage_status(profile_name: str | None = None) -> StorageStatusResult:
    """Get current storage status for a profile, including conflict and pending operation checks.

    Ordinary use in file mode never opens the OS credential store.
    """
    resolved_profile = (profile_name or get_config().auth.default_profile).strip()
    try:
        validate_profile_name(resolved_profile, strict=False)
    except ValueError as e:
        raise ValidationError(str(e)) from e

    from notebooklm_tools.core.auth_migration import get_raw_on_disk_storage_mode

    mode = get_raw_on_disk_storage_mode(resolved_profile)

    profile_dir = get_profile_dir(resolved_profile, create=False)
    has_marker = (profile_dir / "storage-mode.json").exists()
    has_ciphertext = (profile_dir / "credentials.enc").exists()
    has_legacy = (profile_dir / "cookies.json").exists() or (profile_dir / "auth.json").exists()

    protected_residue = False
    has_conflict = False
    conflict_details = None

    if mode == "file":
        # In file mode, ordinary use must never open the OS store.
        # Report residue without opening the store.
        if has_ciphertext:
            protected_residue = True
            conflict_details = (
                "Protected residue present (credentials.enc). "
                f"Run 'nlm auth storage resolve file --profile {resolved_profile}' to clean up."
            )
    elif mode == "protected" and has_legacy and has_ciphertext:
        from notebooklm_tools.core.auth_migration import (
            canonical_secrets_equal,
            capture_file_mode_snapshot,
            capture_protected_snapshot,
        )

        try:
            snap_file = capture_file_mode_snapshot(resolved_profile)
            snap_prot = capture_protected_snapshot(resolved_profile)
            if snap_file and snap_prot and not canonical_secrets_equal(snap_file, snap_prot):
                has_conflict = True
                conflict_details = "Plaintext and protected copies differ in secret values."
        except Exception as exc:
            has_conflict = True
            conflict_details = f"Conflict verification error: {exc}"

    from notebooklm_tools.core.auth_migration import read_operation_marker

    marker = read_operation_marker(resolved_profile)
    has_pending_op = marker is not None
    pending_op_details = None
    if marker:
        if marker.get("corrupt"):
            pending_op_details = (
                f"Corrupt or unreadable operation marker at '{marker.get('marker_path')}'. "
                f"Run 'nlm auth storage resolve --clear-marker --profile {resolved_profile}' to clear it."
            )
        else:
            pending_op_details = (
                f"Operation '{marker.get('operation')}' in phase '{marker.get('phase')}' "
                f"started at {marker.get('timestamp')}."
            )

    return StorageStatusResult(
        profile=resolved_profile,
        mode=mode,
        has_marker=has_marker,
        has_ciphertext=has_ciphertext,
        has_legacy=has_legacy,
        protected_residue=protected_residue,
        has_conflict=has_conflict,
        conflict_details=conflict_details,
        has_pending_op=has_pending_op,
        pending_op_details=pending_op_details,
    )


def set_storage_mode(mode: str, profile_name: str | None = None) -> StorageSetResult:
    """Set the storage mode for a profile, executing migration when needed."""
    resolved_profile = (profile_name or get_config().auth.default_profile).strip()
    mode_clean = mode.strip().lower()
    if mode_clean not in ("protected", "file"):
        raise ValidationError(f"Invalid storage mode '{mode}'. Must be 'protected' or 'file'")

    from notebooklm_tools.core.auth_migration import (
        canonical_secrets_equal,
        capture_file_mode_snapshot,
        capture_protected_snapshot,
        read_operation_marker,
    )

    current_status = get_storage_status(resolved_profile)
    current_mode = current_status["mode"]

    env_mode = os.environ.get("NLM_AUTH_STORAGE", "").strip().lower()
    if env_mode and env_mode in ("file", "protected") and env_mode != current_mode:
        raise ServiceError(
            f"NLM_AUTH_STORAGE environment variable ('{env_mode}') disagrees with on-disk storage mode "
            f"('{current_mode}') for profile '{resolved_profile}'. Unset NLM_AUTH_STORAGE before changing storage mode."
        )

    marker = read_operation_marker(resolved_profile)
    if marker:
        if marker.get("corrupt"):
            raise ServiceError(
                f"Cannot change storage mode: profile '{resolved_profile}' has a corrupt operation marker at '{marker.get('marker_path')}'. "
                f"Run 'nlm auth storage resolve --clear-marker --profile {resolved_profile}' to clear it."
            )
        raise ServiceError(
            f"Cannot change storage mode: profile '{resolved_profile}' has an unfinished operation in progress. "
            f"Run 'nlm auth storage resolve --profile {resolved_profile}' or inspect 'nlm auth storage status' first."
        )

    if mode_clean == current_mode:
        if mode_clean == "file":
            if current_status["has_ciphertext"]:
                snap_file = capture_file_mode_snapshot(resolved_profile)
                snap_prot = capture_protected_snapshot(resolved_profile)
                if snap_file and snap_prot and canonical_secrets_equal(snap_file, snap_prot):
                    # Clean up identical residue
                    enc_file = get_profile_dir(resolved_profile) / "credentials.enc"
                    if enc_file.exists():
                        enc_file.unlink()
                    from notebooklm_tools.core.credential_store import CredentialStore

                    store = CredentialStore()
                    with contextlib.suppress(Exception):
                        store.delete_credentials(resolved_profile)
                    return StorageSetResult(
                        profile=resolved_profile,
                        mode="file",
                        status="updated",
                        message=f"Storage mode is already 'file' for profile '{resolved_profile}'. Cleaned up identical protected residue.",
                    )
                else:
                    raise ServiceError(
                        f"Conflict detected for profile '{resolved_profile}': active file-mode credentials differ from protected residue.\n"
                        f"Choose which credentials to keep:\n"
                        f"  nlm auth storage resolve file --profile {resolved_profile}: keeps your current plain-file login, deletes the encrypted leftover, stays in file mode.\n"
                        f"  nlm auth storage resolve protected --profile {resolved_profile}: keeps the encrypted login, deletes the plain files, switches to Protected mode."
                    )
            return StorageSetResult(
                profile=resolved_profile,
                mode="file",
                status="unchanged",
                message=f"Profile '{resolved_profile}' is already in file mode.",
            )
        else:
            # mode_clean == "protected"
            if current_status["has_legacy"]:
                snap_file = capture_file_mode_snapshot(resolved_profile)
                snap_prot = capture_protected_snapshot(resolved_profile)
                if snap_file and snap_prot and canonical_secrets_equal(snap_file, snap_prot):
                    # Clean up identical plaintext residue
                    cookies_file = get_profile_dir(resolved_profile) / "cookies.json"
                    if cookies_file.exists():
                        cookies_file.unlink()
                    legacy_auth = get_profile_dir(resolved_profile) / "auth.json"
                    if legacy_auth.exists():
                        legacy_auth.unlink()
                    return StorageSetResult(
                        profile=resolved_profile,
                        mode="protected",
                        status="updated",
                        message=f"Storage mode is already 'protected' for profile '{resolved_profile}'. Cleaned up identical plaintext residue.",
                    )
                else:
                    raise ServiceError(
                        f"Conflict detected for profile '{resolved_profile}': active protected credentials differ from plaintext residue. "
                        f"Run 'nlm auth storage resolve [file|protected] --profile {resolved_profile}' to choose which copy to keep."
                    )
            return StorageSetResult(
                profile=resolved_profile,
                mode="protected",
                status="unchanged",
                message=f"Profile '{resolved_profile}' is already in protected mode.",
            )

    # When transitioning from file to protected:
    if mode_clean == "protected":
        try:
            validate_profile_name(resolved_profile, strict=True)
        except ValueError as exc:
            raise ValidationError(
                f"Profile name '{resolved_profile}' contains characters unsupported by protected mode. "
                f"Please rename it first with 'nlm login profile rename \"{resolved_profile}\" <new_name>'."
            ) from exc

        # If ciphertext already exists when switching to protected, check for conflict
        if current_status["has_ciphertext"] and current_status["has_legacy"]:
            snap_file = capture_file_mode_snapshot(resolved_profile)
            snap_prot = capture_protected_snapshot(resolved_profile)
            if snap_file and snap_prot and not canonical_secrets_equal(snap_file, snap_prot):
                raise ServiceError(
                    f"Conflict detected for profile '{resolved_profile}': file-mode credentials differ from existing ciphertext. "
                    f"Run 'nlm auth storage resolve [file|protected] --profile {resolved_profile}' to choose which copy to keep."
                )

        from notebooklm_tools.core.auth_migration import migrate_profile_to_protected
        from notebooklm_tools.core.credential_store import (
            BackendUnavailableError,
            CredentialStoreError,
        )

        try:
            res = migrate_profile_to_protected(resolved_profile)
            msg = f"Storage mode set to 'protected' for profile '{resolved_profile}'."
            removed = list(res.get("removed_files") or [])
            if removed:
                one = len(removed) == 1
                msg += (
                    f" Its plain login file{'' if one else 's'} ({', '.join(removed)}) "
                    f"{'was' if one else 'were'} replaced by the encrypted copy."
                )
            return StorageSetResult(
                profile=resolved_profile,
                mode="protected",
                status="updated",
                message=msg,
            )
        except BackendUnavailableError as exc:
            raise ServiceError(str(exc)) from exc
        except CredentialStoreError as exc:
            raise ServiceError(f"Failed to migrate profile to protected mode: {exc}") from exc

    try:
        validate_profile_name(resolved_profile, strict=False)
    except ValueError as e:
        raise ValidationError(str(e)) from e

    # mode == "file" (switching from protected to file)
    # If legacy files already exist when switching to file, check for conflict
    if current_status["has_ciphertext"] and current_status["has_legacy"]:
        snap_file = capture_file_mode_snapshot(resolved_profile)
        snap_prot = capture_protected_snapshot(resolved_profile)
        if snap_file and snap_prot and not canonical_secrets_equal(snap_file, snap_prot):
            raise ServiceError(
                f"Conflict detected for profile '{resolved_profile}': protected credentials differ from existing plaintext. "
                f"Run 'nlm auth storage resolve [file|protected] --profile {resolved_profile}' to choose which copy to keep."
            )

    from notebooklm_tools.core.auth_migration import migrate_profile_to_file
    from notebooklm_tools.core.credential_store import (
        BackendUnavailableError,
        CredentialStoreError,
    )

    try:
        res = migrate_profile_to_file(resolved_profile)
        return StorageSetResult(
            profile=resolved_profile,
            mode="file",
            status="updated",
            message=res.get("message")
            or f"Storage mode set to 'file' for profile '{resolved_profile}'.",
        )
    except BackendUnavailableError as exc:
        raise ServiceError(str(exc)) from exc
    except CredentialStoreError as exc:
        raise ServiceError(f"Failed to switch profile to file mode: {exc}") from exc


def resolve_storage_conflict(
    profile_name: str,
    choice: str | None = None,
    discard_inaccessible: bool = False,
    clear_marker: bool = False,
) -> StorageSetResult:
    """Resolve a conflict where both plaintext and protected credentials exist."""
    from notebooklm_tools.core.auth_migration import (
        _get_operations_dir,
        clear_operation_marker,
        get_raw_on_disk_storage_mode,
        read_operation_marker,
    )
    from notebooklm_tools.core.credential_backend_worker import BackendTimeoutError
    from notebooklm_tools.core.credential_store import (
        BackendUnavailableError,
        CredentialStore,
        CredentialStoreError,
        get_profile_lock,
    )

    validate_profile_name(profile_name, strict=False)

    if clear_marker:
        with get_profile_lock(profile_name):
            marker = read_operation_marker(profile_name)
            if not marker:
                raise ServiceError(f"No operation marker found for profile '{profile_name}'.")

            # Refuse if quarantine folder for this profile exists and contains files
            quarantine_root = _get_operations_dir() / "quarantine"
            if quarantine_root.exists():
                for q_cand in quarantine_root.iterdir():
                    if q_cand.is_dir() and q_cand.name.startswith(f"{profile_name}_"):
                        files = sorted(f.name for f in q_cand.iterdir() if f.is_file())
                        if files:
                            mappings = []
                            for f_name in files:
                                if f_name == "root_auth.json":
                                    mappings.append("root_auth.json → auth.json")
                                else:
                                    mappings.append(f"{f_name} → profiles/{profile_name}/{f_name}")
                            mapping_str = ", ".join(mappings)
                            raise ServiceError(
                                f"Cannot clear marker: quarantine folder '{q_cand}' contains credentials files "
                                f"({', '.join(files)}). Clearing the marker could delete or abandon the only "
                                f"plaintext copy. Inspect or restore them first:\n  {mapping_str}"
                            )

            clear_operation_marker(profile_name)
            return StorageSetResult(
                profile=profile_name,
                mode=get_raw_on_disk_storage_mode(profile_name),
                status="resolved",
                message=f"Operation marker cleared for profile '{profile_name}'.",
            )

    if not choice:
        raise ValidationError("Resolution choice ('file' or 'protected') must be specified")

    choice_clean = choice.strip().lower()
    if choice_clean not in ("file", "protected"):
        raise ValidationError(
            f"Invalid resolution choice '{choice}'. Must be 'file' or 'protected'"
        )

    validate_profile_name(profile_name, strict=(choice_clean == "protected"))

    env_mode = os.environ.get("NLM_AUTH_STORAGE", "").strip().lower()
    disk_mode = get_raw_on_disk_storage_mode(profile_name)
    if env_mode and env_mode in ("file", "protected") and env_mode != disk_mode:
        raise ServiceError(
            f"NLM_AUTH_STORAGE environment variable ('{env_mode}') disagrees with on-disk storage mode "
            f"('{disk_mode}') for profile '{profile_name}'. Unset NLM_AUTH_STORAGE before resolving conflict."
        )

    with get_profile_lock(profile_name):
        marker = read_operation_marker(profile_name)
        if marker:
            if marker.get("corrupt"):
                raise ServiceError(
                    f"Profile '{profile_name}' has a corrupt operation marker at '{marker.get('marker_path')}'. "
                    f"Run 'nlm auth storage resolve --clear-marker --profile {profile_name}' to clear it."
                )
            raise ServiceError(
                f"Cannot resolve storage conflict: profile '{profile_name}' has an unfinished operation in progress. "
                "Inspect 'nlm auth storage status' first."
            )

        profile_dir = get_profile_dir(profile_name, create=False)
        enc_path = profile_dir / "credentials.enc"
        cookies_path = profile_dir / "cookies.json"
        legacy_auth = profile_dir / "auth.json"

        store = CredentialStore()

        if choice_clean == "protected":
            if not enc_path.exists():
                raise ServiceError(
                    f"Cannot resolve to 'protected': no ciphertext exists for profile '{profile_name}'."
                )
            payload = store.read_credentials(profile_name)
            if not payload:
                raise ServiceError(
                    f"Cannot resolve to 'protected': ciphertext for profile '{profile_name}' cannot be decrypted."
                )
            if cookies_path.exists():
                with contextlib.suppress(OSError):
                    cookies_path.unlink()
            if legacy_auth.exists():
                with contextlib.suppress(OSError):
                    legacy_auth.unlink()
            configured_default = get_config().auth.default_profile
            if profile_name == configured_default:
                root_auth = get_storage_dir() / "auth.json"
                if root_auth.exists() and not root_auth.is_symlink():
                    with contextlib.suppress(OSError):
                        root_auth.unlink()

            set_auth_storage_mode(profile_name, "protected")
            return StorageSetResult(
                profile=profile_name,
                mode="protected",
                status="resolved",
                message=f"Conflict resolved: profile '{profile_name}' is now in protected mode (plain files removed).",
            )
        else:
            # choice == "file"
            if discard_inaccessible:
                # Preflight check on ciphertext readability
                if enc_path.exists():
                    try:
                        payload = store.read_credentials(profile_name)
                        if payload and payload.get("cookies"):
                            raise ServiceError(
                                f"Cannot discard credentials: protected credentials for profile '{profile_name}' are healthy and readable. "
                                f"To export them to file mode without losing credentials, run 'nlm auth storage set file --profile {profile_name}' "
                                f"or 'nlm auth storage resolve file --profile {profile_name}' without --discard-inaccessible."
                            )
                    except ServiceError:
                        raise
                    except (BackendUnavailableError, BackendTimeoutError) as exc:
                        raise ServiceError(
                            f"Cannot discard credentials for profile '{profile_name}': OS credential backend is locked, unavailable, or timed out ({exc}). "
                            "Unlock your keystore or run this command from your desktop session."
                        ) from exc
                    except Exception as exc:
                        err_str = str(exc).lower()
                        if (
                            "locked" in err_str
                            or "unavailable" in err_str
                            or "timed out" in err_str
                        ):
                            raise ServiceError(
                                f"Cannot discard credentials for profile '{profile_name}': OS credential backend is locked, unavailable, or timed out ({exc}). "
                                "Unlock your keystore or run this command from your desktop session."
                            ) from exc

                if enc_path.exists():
                    with contextlib.suppress(OSError):
                        enc_path.unlink()
                with contextlib.suppress(Exception):
                    store.delete_credentials(profile_name)
                set_auth_storage_mode(profile_name, "file")
                return StorageSetResult(
                    profile=profile_name,
                    mode="file",
                    status="resolved",
                    message=(
                        f"Inaccessible credentials discarded. Storage mode set to 'file' for profile '{profile_name}'. "
                        "Run 'nlm login' to re-authenticate."
                    ),
                )

            if cookies_path.exists():
                if enc_path.exists():
                    with contextlib.suppress(OSError):
                        enc_path.unlink()
                with contextlib.suppress(Exception):
                    store.delete_credentials(profile_name)
                set_auth_storage_mode(profile_name, "file")
                return StorageSetResult(
                    profile=profile_name,
                    mode="file",
                    status="resolved",
                    message=f"Conflict resolved: profile '{profile_name}' is now in file mode (ciphertext removed).",
                )
            else:
                from notebooklm_tools.core.auth_migration import migrate_profile_to_file

                try:
                    migrate_profile_to_file(profile_name)
                    return StorageSetResult(
                        profile=profile_name,
                        mode="file",
                        status="resolved",
                        message=f"Conflict resolved: profile '{profile_name}' is now in file mode (credentials exported).",
                    )
                except (BackendUnavailableError, CredentialStoreError) as exc:
                    raise ServiceError(
                        f"Cannot decrypt protected credentials to export to file mode: {exc}\n"
                        f"To discard inaccessible ciphertext and return to file mode, run:\n"
                        f"nlm auth storage resolve file --discard-inaccessible --profile {profile_name}"
                    ) from exc


def relocate_storage(storage_dir: Path | None = None) -> dict[str, Any]:
    """Relocate the installation identity to match a moved storage directory."""
    from notebooklm_tools.core.credential_store import relocate_installation

    identity = relocate_installation(storage_dir=storage_dir)
    return {
        "canonical_root": identity.canonical_root,
        "installation_id": identity.installation_id,
        "backend_id": identity.backend_id,
        "message": f"Installation canonical root relocated to '{identity.canonical_root}'.",
    }


class RenameProfileResult(TypedDict):
    """Result of renaming an auth profile."""

    old_name: str
    new_name: str
    is_default: bool
    message: str


def rename_profile(old_name: str, new_name: str) -> RenameProfileResult:
    """Rename an authentication profile.

    Validates names, orchestrates profile migration, reads storage-mode.json
    directly from disk (bypassing NLM_AUTH_STORAGE env var to avoid persisting
    environment overrides), updates default_profile if needed, and deletes the old profile.
    """
    import json

    from notebooklm_tools.core.auth_migration import read_operation_marker
    from notebooklm_tools.services.errors import ConflictError, NotFoundError
    from notebooklm_tools.utils.config import get_profiles_dir, save_config

    old_clean = old_name.strip()
    new_clean = new_name.strip()

    try:
        validate_profile_name(old_clean, strict=False)
        validate_profile_name(new_clean, strict=False)
    except ValueError as e:
        raise ValidationError(str(e)) from e

    config = get_config()
    profiles_dir = get_profiles_dir()
    old_dir = profiles_dir / old_clean
    new_dir = profiles_dir / new_clean

    if not old_dir.exists():
        raise NotFoundError(f"Profile '{old_clean}' does not exist")

    # Guard: check if an unfinished or corrupt operation marker exists
    marker = read_operation_marker(old_clean)
    if marker:
        if marker.get("corrupt"):
            raise ServiceError(
                f"Cannot rename profile '{old_clean}': profile has a corrupt operation marker at '{marker.get('marker_path')}'. "
                f"Run 'nlm auth storage resolve --clear-marker --profile {old_clean}' to clear it."
            )
        raise ServiceError(
            f"Cannot rename profile '{old_clean}': an unfinished storage operation is in progress. "
            f"Run 'nlm auth storage status --profile {old_clean}' first."
        )

    # Protected profiles cannot be renamed yet
    if (old_dir / "credentials.enc").exists():
        raise ServiceError("Renaming protected profiles is coming in a later update.")

    raw_mode_file = old_dir / "storage-mode.json"
    if raw_mode_file.exists():
        try:
            mode_data = json.loads(raw_mode_file.read_text(encoding="utf-8"))
            if isinstance(mode_data, dict) and mode_data.get("mode") == "protected":
                raise ServiceError("Renaming protected profiles is coming in a later update.")
        except ServiceError:
            raise
        except Exception:
            pass

    if new_dir.exists():
        raise ConflictError(f"Profile '{new_clean}' already exists")

    storage_dir = get_storage_dir()

    def _browser_profile_dirs(name: str) -> list[Path]:
        # Saved browser logins that belong to this auth profile. Preserve the
        # legacy default-profile location when it already exists.
        legacy = storage_dir / "chrome-profile"
        chrome = legacy if name == "default" and legacy.exists() else None
        return [
            chrome or storage_dir / "chrome-profiles" / name,
            storage_dir / "firefox-profiles" / name,
        ]

    # Pair each old browser dir with its new location. A destination that
    # already exists belongs to someone else, so refuse before moving anything.
    browser_moves: list[tuple[Path, Path]] = []
    for old_path, new_path in zip(
        _browser_profile_dirs(old_clean), _browser_profile_dirs(new_clean), strict=True
    ):
        if new_path.exists():
            raise ConflictError(
                f"Browser profile '{new_clean}' already exists ({new_path.parent.name}); "
                "refusing to attach another browser identity to this profile"
            )
        if old_path.exists():
            browser_moves.append((old_path, new_path))

    def _move_dir(source: Path, destination: Path) -> None:
        try:
            source.rename(destination)
        except OSError:
            import shutil

            shutil.move(str(source), str(destination))

    browsers_moved: list[tuple[Path, Path]] = []
    auth_moved = False
    is_default = config.auth.default_profile == old_clean

    try:
        # Keep the saved browser identities aligned with the auth profile. Move
        # them first so an auth-rename failure can restore the browser dirs.
        for old_path, new_path in browser_moves:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            _move_dir(old_path, new_path)
            browsers_moved.append((old_path, new_path))

        _move_dir(old_dir, new_dir)
        auth_moved = True

        if is_default:
            config.auth.default_profile = new_clean
            save_config(config)
    except Exception as exc:
        rollback_errors: list[str] = []

        if is_default:
            config.auth.default_profile = old_clean

        if auth_moved and new_dir.exists() and not old_dir.exists():
            try:
                _move_dir(new_dir, old_dir)
            except Exception as rollback_exc:
                rollback_errors.append(f"auth profile: {rollback_exc}")

        for old_path, new_path in reversed(browsers_moved):
            if new_path.exists() and not old_path.exists():
                try:
                    old_path.parent.mkdir(parents=True, exist_ok=True)
                    _move_dir(new_path, old_path)
                except Exception as rollback_exc:
                    rollback_errors.append(
                        f"browser profile {old_path.parent.name}: {rollback_exc}"
                    )

        if rollback_errors:
            raise ServiceError(
                "Profile rename failed and rollback was incomplete: " + "; ".join(rollback_errors)
            ) from exc
        raise

    msg = f"Renamed profile '{old_clean}' to '{new_clean}'"
    if is_default:
        msg += " and set as default profile"

    return RenameProfileResult(
        old_name=old_clean,
        new_name=new_clean,
        is_default=is_default,
        message=msg,
    )


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def find_plain_backup_files(
    profile_name: str,
    storage_dir: Path | None = None,
    home_dir: Path | None = None,
) -> list[Path]:
    """Find leftover plaintext login backup files for a profile.

    IMPORTANT: Never touches the `backups/` directory, which holds `nlm setup`'s
    MCP-config and skill backups.

    Only includes files that match specific known backup locations AND provably parse
    as JSON containing login credential keys:
    - `auth.json.backup-*` directly in the storage root
    - `cookies.json.bak`, `auth.json.bak`, or `metadata.json.bak` inside that profile's folder
    - Legacy `~/.notebooklm-mcp/auth.json` and `auth.json.backup*`

    Login files come in two shapes: a dict with a "cookies" key, or a list of
    cookie objects (each with "name" and "value"), as saved in cookies.json.
    """
    from notebooklm_tools.utils.config import (
        get_home_dir,
        get_legacy_storage_dir,
        get_storage_dir,
    )

    root = storage_dir if storage_dir is not None else get_storage_dir()

    candidates: list[Path] = []

    # 1. Root auth.json.backup-* (directly in root, NOT inside backups/ or subdirectories)
    if root.exists():
        for item in root.glob("auth.json.backup-*"):
            if item.is_file() and not item.is_symlink():
                candidates.append(item)

    # 2. Profile folder backups
    profile_dir = root / "profiles" / profile_name
    if profile_dir.exists():
        for name in ("cookies.json.bak", "auth.json.bak", "metadata.json.bak"):
            target = profile_dir / name
            if target.is_file() and not target.is_symlink():
                candidates.append(target)

    # 3. Legacy ~/.notebooklm-mcp/auth.json and its auth.json.backup* copies.
    # Only when storage is at its normal home location: a custom storage path
    # (sandbox, test, server) must never pull in the real home's legacy files.
    legacy_files: list[Path] = []
    if home_dir is not None:
        legacy_dir: Path | None = home_dir / ".notebooklm-mcp"
    elif _same_path(root, get_home_dir() / ".notebooklm-mcp-cli"):
        legacy_dir = get_legacy_storage_dir()
    else:
        legacy_dir = None
    if legacy_dir is not None:
        legacy_files.append(legacy_dir / "auth.json")
        if legacy_dir.is_dir():
            legacy_files += sorted(legacy_dir.glob("auth.json.backup*"))
    for legacy_file in legacy_files:
        if legacy_file.is_file() and not legacy_file.is_symlink():
            candidates.append(legacy_file)

    def _is_cookie_list(data: object) -> bool:
        return (
            isinstance(data, list)
            and bool(data)
            and all(isinstance(c, dict) and "name" in c and "value" in c for c in data)
        )

    valid_files: list[Path] = []
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if path.name == "metadata.json.bak":
                if isinstance(data, dict) and ("csrf_token" in data or "session_id" in data):
                    valid_files.append(path)
            elif (isinstance(data, dict) and "cookies" in data) or _is_cookie_list(data):
                valid_files.append(path)
        except Exception:
            continue

    return sorted(valid_files)


def remove_plain_backup_files(files: list[Path]) -> list[Path]:
    """Remove candidate plaintext backup files safely.

    Never deletes directories or symlinks.
    """
    removed: list[Path] = []
    for file in files:
        if file.is_file() and not file.is_symlink():
            try:
                file.unlink()
                removed.append(file)
            except OSError:
                pass
    return removed


def saved_profile_names() -> list[str]:
    """Sorted names of profiles that really hold saved credentials (no marker-only ghosts)."""
    from notebooklm_tools.services.auth import AuthManager

    return sorted(n for n in AuthManager.list_profiles() if AuthManager(n).profile_exists())


def keystore_available() -> bool:
    """Fresh keystore probe (writes and deletes a throwaway entry). Call only right before
    an explicit, user-requested protect action — never from listing or status code."""
    from notebooklm_tools.core.credential_store import CredentialStore

    return CredentialStore().is_available()


def record_protect_choice(profile_name: str, protected: bool) -> None:
    """Remember the user's protect answer so no protection nudge asks about this profile again."""
    from notebooklm_tools.core.notices import record_protect_answer

    record_protect_answer(profile_name, "yes" if protected else "no")


def protected_name_problem(profile_name: str) -> str | None:
    """Why this name can't be a protected profile, or None if it can."""
    try:
        validate_profile_name(profile_name, strict=True)
    except ValueError as exc:
        return str(exc)
    return None


def suggest_protected_name(profile_name: str) -> str | None:
    """A protected-mode-safe name derived from an unusable one (my work -> my-work), or None.

    None when nothing usable is left, the suggestion is itself rejected (reserved name,
    case-insensitive clash with a saved profile), or a profile with that name already exists.
    """
    import re

    candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", (profile_name or "").strip()).strip("-.")
    if not candidate or protected_name_problem(candidate) is not None:
        return None
    if candidate in saved_profile_names():
        return None
    return candidate


def is_desktop_session() -> bool:
    """Cheap hints only (no keystore probe): False on SSH, containers, headless Linux."""
    from notebooklm_tools.core.credential_backend_worker import is_definitely_non_desktop

    return not is_definitely_non_desktop()


def mark_new_profile_protected(profile_name: str) -> None:
    """Mark a not-yet-saved profile as protected so its first save goes to the keystore."""
    set_auth_storage_mode(profile_name, "protected")


def discard_unsaved_profile(profile_name: str) -> None:
    """Undo mark_new_profile_protected after a failed first login. Never touches saved credentials."""
    from notebooklm_tools.services.auth import AuthManager

    if AuthManager(profile_name).profile_exists():
        return
    pdir = get_profile_dir(profile_name, create=False)
    marker = pdir / "storage-mode.json"
    if marker.exists():
        marker.unlink()
    with contextlib.suppress(OSError):
        pdir.rmdir()  # only succeeds when empty


# ---------------------------------------------------------------------------
# Re-exports from `core.credential_store` for `cli/` and `mcp/` (layering shim).
# ---------------------------------------------------------------------------

_CREDENTIAL_SYMBOLS = frozenset({"CredentialStore", "get_backend_factory", "get_envelope_revision"})


def __getattr__(name: str):
    """PEP 562 lazy re-export of credential store symbols from `core`."""
    if name in _CREDENTIAL_SYMBOLS:
        from notebooklm_tools.core import credential_store as _core_credential_store

        return getattr(_core_credential_store, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
