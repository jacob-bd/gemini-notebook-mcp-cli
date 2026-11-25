"""Downloads service — shared validation and routing for artifact downloads."""

import asyncio
import inspect
import os
import re
import tempfile
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast

from ..core.client import NotebookLMClient
from ..core.errors import ArtifactDownloadError, ClientAuthenticationError
from ..utils.config import get_home_dir, get_storage_dir
from ._compat import TypedDict
from .errors import ServiceError, ValidationError
from .notebooks import get_notebook, list_notebooks
from .studio import get_studio_status

VALID_ARTIFACT_TYPES = (
    "audio",
    "video",
    "report",
    "interactive_report",
    "mind_map",
    "slide_deck",
    "infographic",
    "data_table",
    "data_table_xlsx",
    "file",
    "quiz",
    "flashcards",
)

VALID_OUTPUT_FORMATS = ("json", "markdown", "html")

# Types that support async streaming downloads with progress callbacks
STREAMING_TYPES = ("audio", "video", "slide_deck", "infographic")

# Types that support output_format (json/markdown/html)
INTERACTIVE_TYPES = ("quiz", "flashcards")

# Extension map per artifact type (used for default filenames)
DEFAULT_EXTENSIONS = {
    "audio": "m4a",
    "video": "mp4",
    "report": "md",
    "interactive_report": "md",
    "mind_map": "json",
    "slide_deck": "pdf",
    "infographic": "png",
    "data_table": "csv",
    "data_table_xlsx": "xlsx",
    "file": "bin",
    "quiz": "json",  # varies by format
    "flashcards": "json",  # varies by format
}

# Extension map for output formats (quiz/flashcards)
FORMAT_EXTENSIONS = {
    "json": "json",
    "markdown": "md",
    "html": "html",
}


class DownloadResult(TypedDict):
    """Result of a download operation."""

    artifact_type: str
    path: str


class DownloadAllItem(TypedDict):
    """Outcome of one artifact download attempted by download_all()."""

    artifact_id: str | None
    artifact_type: str
    title: str
    path: str
    success: bool
    error: str | None


class SkippedArtifact(TypedDict):
    """An artifact download_all() saw but did not attempt to download."""

    artifact_id: str | None
    artifact_type: str
    title: str
    reason: str


class DownloadAllResult(TypedDict):
    """Result of downloading all artifacts of a notebook."""

    notebook_id: str
    notebook_title: str
    output_dir: str
    items: list[DownloadAllItem]
    skipped: list[SkippedArtifact]
    total_artifacts: int
    downloaded: int
    failed: int


class NotebookSweepItem(TypedDict):
    """Per-notebook outcome of a download_all_notebooks() sweep."""

    notebook_id: str
    notebook_title: str
    output_dir: str | None
    downloaded: int
    failed: int
    skipped: int
    error: str | None


class DownloadAllNotebooksResult(TypedDict):
    """Result of sweeping every notebook with download_all()."""

    output_dir: str
    notebooks: list[NotebookSweepItem]
    total_notebooks: int
    downloaded: int
    failed: int
    errored_notebooks: int


# Directories that are always blocked as download targets, regardless of platform.
_BLOCKED_DIRS = {
    ".ssh",
    ".gnupg",
    ".claude",
    ".config",
    ".aws",
    ".kube",
    # Agent instruction and skill directories: files here are read as
    # instructions by other tools, so a write is an injection vector.
    ".codex",
    ".cursor",
    ".gemini",
    ".agents",
    ".cline",
    ".windsurf",
    ".github",
    # Things that get executed.
    ".local",
    ".git",
    ".docker",
    "LaunchAgents",
    "LaunchDaemons",
}


_SENSITIVE_FILES = {
    ".bashrc",
    ".zshrc",
    ".profile",
    ".bash_profile",
    ".gitconfig",
    "authorized_keys",
    "known_hosts",
    "id_rsa",
    "id_ed25519",
    # Added for GHSA-92q4-9x75-55rf.
    ".zshenv",
    ".zprofile",
    ".zlogin",
    ".zlogout",
    ".bash_login",
    ".bash_logout",
    ".netrc",
    ".npmrc",
    ".pypirc",
}

_MISMATCHED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".aiff", ".wma"}


def validate_audio_extension(output_path: str) -> None:
    """Reject output extensions that don't match NotebookLM's AAC-in-MP4 audio format.

    NotebookLM Studio delivers audio as AAC inside an MP4/M4A container.
    Writing that stream to a `.mp3` (or other incompatible) extension produces
    a file whose bytes don't match the extension, breaking downstream tools.

    Raises ValidationError with a helpful message and ffmpeg workaround.
    """
    suffix = Path(output_path).suffix.lower()
    if suffix in _MISMATCHED_AUDIO_EXTENSIONS:
        raise ValidationError(
            f"NotebookLM delivers AAC audio in an MP4 container; "
            f"cannot honor '{suffix}' suffix.\n"
            f"Re-run with a .m4a or .mp4 suffix, or transcode with ffmpeg:\n"
            f"  nlm download audio <id> -o raw.m4a\n"
            f"  ffmpeg -i raw.m4a -acodec libmp3lame -q:a 2 podcast.mp3",
        )


def resolve_download_root() -> Path:
    """Resolve the directory that enforced downloads are confined to.

    Order:
      1. ``NOTEBOOKLM_DOWNLOAD_DIR`` when the operator set one.
      2. ``~/Downloads/gemini-notebook`` when ``~/Downloads`` already exists.
      3. The app storage directory otherwise.

    Step 2 deliberately never creates ``~/Downloads``. Headless Linux boxes,
    containers, localized desktops, and Windows installs with a relocated
    Downloads Known Folder have no such directory, and inventing one there
    would scatter files somewhere the user does not look.
    """
    if configured := str(os.environ.get("NOTEBOOKLM_DOWNLOAD_DIR") or "").strip():
        return Path(configured).expanduser()

    downloads = get_home_dir() / "Downloads"
    if downloads.is_dir():
        return downloads / "gemini-notebook"
    return get_storage_dir() / "downloads"


def _is_within(candidate: Path, root: Path) -> bool:
    """Containment check that survives case-insensitive filesystems.

    Windows and macOS compare paths case-insensitively, so a plain string or
    ``is_relative_to`` comparison rejects legitimate paths that differ only in
    case. That fails closed rather than open, but it still breaks downloads.
    """
    normalized = os.path.normcase(str(candidate))
    normalized_root = os.path.normcase(str(root)).rstrip(os.sep)
    return normalized == normalized_root or normalized.startswith(normalized_root + os.sep)


def validate_output_path(output_path: str, *, enforce_root: bool = False) -> str:
    """Validate an output path and return the absolute path to write to.

    Callers MUST write to the returned path. Writing to the original string
    instead re-derives a path that was never checked, which is how a denylist
    bypass turns back into an arbitrary write.

    ``enforce_root`` confines the path to :func:`resolve_download_root`, and
    anchors relative paths there instead of the process working directory. MCP
    callers set it because the model chooses the path and untrusted source
    content can steer that choice. CLI callers leave it off: the human typed
    the path, so the denylist and the optional ``NOTEBOOKLM_DOWNLOAD_DIR``
    boundary are the appropriate level of protection there.

    Raises:
        ValidationError: If the path escapes its boundary or targets a
            sensitive location.
    """
    root = resolve_download_root() if enforce_root else None

    candidate = Path(output_path).expanduser()
    if root is not None and not candidate.is_absolute():
        candidate = root / candidate

    # resolve() follows symlinks in existing ancestors, so a symlink planted
    # inside the root cannot be used to hop outside it.
    resolved = candidate.resolve()

    if root is not None:
        if not _is_within(resolved, root.resolve()):
            raise ValidationError(
                f"Refusing to write outside the download directory. "
                f"'{resolved}' is not inside '{root}'. "
                f"Set NOTEBOOKLM_DOWNLOAD_DIR to choose a different location."
            )
        return str(resolved)

    download_dir_env = os.environ.get("NOTEBOOKLM_DOWNLOAD_DIR", "")
    if download_dir_env:
        download_root = Path(download_dir_env).expanduser().resolve()
        if not _is_within(resolved, download_root):
            raise ValidationError(
                f"Output path '{resolved}' is outside download directory "
                f"'{download_root}'. Set NOTEBOOKLM_DOWNLOAD_DIR to change."
            )

    # Second layer for CLI callers. This list can never be complete, which is
    # exactly why enforce_root exists for anything the model drives.
    for part in resolved.parts:
        if part in _BLOCKED_DIRS:
            raise ValidationError(
                f"Refusing to write to sensitive directory: {resolved}. "
                f"Choose a different output path."
            )

    if resolved.name in _SENSITIVE_FILES:
        raise ValidationError(
            f"Refusing to overwrite sensitive file: {resolved.name}. "
            f"Choose a different output path."
        )

    return str(resolved)


def validate_artifact_type(artifact_type: str) -> None:
    """Validate artifact type. Raises ValidationError if invalid."""
    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise ValidationError(
            f"Unknown artifact type '{artifact_type}'. "
            f"Valid types: {', '.join(VALID_ARTIFACT_TYPES)}",
        )


def validate_output_format(output_format: str) -> None:
    """Validate output format for interactive types. Raises ValidationError if invalid."""
    if output_format not in VALID_OUTPUT_FORMATS:
        raise ValidationError(
            f"Invalid output format '{output_format}'. "
            f"Valid formats: {', '.join(VALID_OUTPUT_FORMATS)}",
        )


def get_default_extension(artifact_type: str, output_format: str = "json") -> str:
    """Get default file extension for an artifact type.

    For interactive types (quiz/flashcards), depends on output_format.
    """
    if artifact_type in INTERACTIVE_TYPES:
        return FORMAT_EXTENSIONS.get(output_format, "json")
    return DEFAULT_EXTENSIONS.get(artifact_type, "bin")


def download_sync(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_type: str,
    output_path: str,
    artifact_id: str | None = None,
    output_format: str = "json",
    *,
    enforce_root: bool = False,
) -> DownloadResult:
    """Download a non-streaming artifact synchronously.

    For: report, mind_map, data_table, data_table_xlsx, quiz, flashcards.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        artifact_type: Type of artifact
        output_path: Path to save file
        artifact_id: Specific artifact ID (optional)
        output_format: For quiz/flashcards: json|markdown|html

    Returns:
        DownloadResult with artifact_type and path

    Raises:
        ValidationError: If artifact_type or output_format is invalid
        ServiceError: If the download fails
    """
    validate_artifact_type(artifact_type)
    safe_path = validate_output_path(output_path, enforce_root=enforce_root)
    if enforce_root:
        # Write to the path containment actually approved, not the raw string.
        output_path = safe_path

    if artifact_type == "audio":
        validate_audio_extension(output_path)

    if artifact_type in INTERACTIVE_TYPES:
        validate_output_format(output_format)

    try:
        saved_path = _dispatch_sync(
            client,
            notebook_id,
            artifact_type,
            output_path,
            artifact_id,
            output_format,
        )
    except (ValidationError, ServiceError):
        raise
    except ClientAuthenticationError as e:
        raise ServiceError(
            f"Failed to download {artifact_type}: {e}",
            user_message=(
                f"Authentication expired while downloading {artifact_type}. "
                "Run 'nlm login' to refresh credentials."
            ),
            hint="Run 'nlm login' to refresh credentials.",
            debug_code="auth_required",
        ) from e
    except Exception as e:
        raise ServiceError(
            f"Failed to download {artifact_type}: {e}",
            user_message=f"Download failed for {artifact_type}.",
        ) from e

    if not saved_path:
        raise ServiceError(
            f"Download returned no path for {artifact_type}",
            user_message=f"{artifact_type} is not ready or does not exist.",
        )

    return {"artifact_type": artifact_type, "path": saved_path}


async def _download_once_async(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_type: str,
    output_path: str,
    artifact_id: str | None,
    output_format: str,
    progress_callback: Callable[[int, int], None] | None,
    slide_deck_format: str,
) -> DownloadResult:
    """Attempt one artifact download without readiness polling."""
    try:
        saved_path = await _dispatch_async(
            client,
            notebook_id,
            artifact_type,
            output_path,
            artifact_id,
            output_format,
            progress_callback,
            slide_deck_format=slide_deck_format,
        )
    except (ValidationError, ServiceError):
        raise
    except ClientAuthenticationError as e:
        raise ServiceError(
            f"Failed to download {artifact_type}: {e}",
            user_message=(
                f"Authentication expired while downloading {artifact_type}. "
                "Run 'nlm login' to refresh credentials."
            ),
            hint="Run 'nlm login' to refresh credentials.",
            debug_code="auth_required",
        ) from e
    except ArtifactDownloadError as e:
        if "still propagating" in e.details.lower():
            raise ServiceError(
                f"Failed to download {artifact_type}: {e}",
                user_message=(
                    f"{artifact_type.title()} is complete, but its media may still be "
                    "propagating or may be unavailable."
                ),
                hint="Retry later; if the 404 persists, verify artifact access.",
                debug_code="artifact_not_ready",
            ) from e
        raise ServiceError(
            f"Failed to download {artifact_type}: {e}",
            user_message=f"Download failed for {artifact_type}.",
        ) from e
    except Exception as e:
        raise ServiceError(
            f"Failed to download {artifact_type}: {e}",
            user_message=f"Download failed for {artifact_type}.",
        ) from e

    if not saved_path:
        raise ServiceError(
            f"Download returned no path for {artifact_type}",
            user_message=f"{artifact_type} is not ready or does not exist.",
            hint="Retry shortly if the artifact was just created.",
            debug_code="artifact_not_ready",
        )

    return {"artifact_type": artifact_type, "path": saved_path}


async def download_async(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_type: str,
    output_path: str,
    artifact_id: str | None = None,
    output_format: str = "json",
    progress_callback: Callable[[int, int], None] | None = None,
    slide_deck_format: str = "pdf",
    *,
    enforce_root: bool = False,
    wait: bool = False,
    wait_timeout: float = 180.0,
    poll_interval: float = 5.0,
) -> DownloadResult:
    """Download a streaming artifact asynchronously.

    For: audio, video, slide_deck, infographic, quiz, flashcards.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        artifact_type: Type of artifact
        output_path: Path to save file
        artifact_id: Specific artifact ID (optional)
        output_format: For quiz/flashcards: json|markdown|html
        progress_callback: Called with (current, total) for progress tracking
        slide_deck_format: For slide_deck only: "pdf" (default) or "pptx"
        wait: Poll while the artifact download is still propagating
        wait_timeout: Service polling budget when ``wait`` is enabled; internal
            CDN retries and the file transfer can extend total wall time
        poll_interval: Seconds between readiness checks

    Returns:
        DownloadResult with artifact_type and path

    Raises:
        ValidationError: If artifact_type, output_format, or polling options are invalid
        ServiceError: If the download fails or readiness times out
    """
    validate_artifact_type(artifact_type)
    safe_path = validate_output_path(output_path, enforce_root=enforce_root)
    if enforce_root:
        # Write to the path containment actually approved, not the raw string.
        output_path = safe_path

    if artifact_type == "audio":
        validate_audio_extension(output_path)
    if artifact_type in INTERACTIVE_TYPES:
        validate_output_format(output_format)
    if wait and wait_timeout < 0:
        raise ValidationError("wait_timeout must be greater than or equal to 0.")
    if wait and poll_interval <= 0:
        raise ValidationError("poll_interval must be greater than 0.")

    deadline = time.monotonic() + wait_timeout
    while True:
        try:
            return await _download_once_async(
                client,
                notebook_id,
                artifact_type,
                output_path,
                artifact_id,
                output_format,
                progress_callback,
                slide_deck_format,
            )
        except ServiceError as e:
            if not wait or e.debug_code != "artifact_not_ready":
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ServiceError(
                    f"{artifact_type} download was not ready after {wait_timeout}s",
                    user_message=f"{artifact_type} is not ready yet.",
                    hint="Retry shortly or increase wait_timeout.",
                    debug_code="artifact_not_ready",
                ) from e
            await asyncio.sleep(min(poll_interval, remaining))


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Windows reserves these device names regardless of extension (CON.md is invalid).
_RESERVED_FILENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_filename(name: str, fallback: str = "untitled", max_length: int = 80) -> str:
    """Turn an artifact/notebook title into a safe cross-platform file name.

    Replaces characters invalid on Windows/POSIX, collapses whitespace, and
    truncates. Returns ``fallback`` if nothing usable remains.
    """
    cleaned = re.sub(r"\s+", " ", name).strip()
    cleaned = _INVALID_FILENAME_CHARS.sub("_", cleaned)
    cleaned = cleaned[:max_length].rstrip(". ")
    if cleaned.upper() in _RESERVED_FILENAMES:
        cleaned = f"_{cleaned}"
    return cleaned or fallback


def validate_slide_deck_format(slide_deck_format: str) -> None:
    """Validate slide deck file format. Raises ValidationError if invalid."""
    if slide_deck_format not in ("pdf", "pptx"):
        raise ValidationError(
            f"Invalid slide deck format '{slide_deck_format}'. Valid formats: pdf, pptx",
        )


async def download_all(
    client: NotebookLMClient,
    notebook_id: str,
    output_dir: str = ".",
    artifact_types: Sequence[str] | None = None,
    output_format: str = "json",
    slide_deck_format: str = "pdf",
    skip_existing: bool = False,
    progress_factory: Callable[[str, str], Callable[[int, int], None] | None] | None = None,
    notebook_dir_name: str | None = None,
    *,
    enforce_root: bool = False,
) -> DownloadAllResult:
    """Download every completed studio artifact of a notebook.

    Creates a subdirectory of ``output_dir`` named after the notebook title
    and saves each artifact there, named after its title with the type's
    default extension. Failures on individual artifacts are recorded and do
    not stop the remaining downloads.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        output_dir: Base directory; the per-notebook directory is created inside
        artifact_types: Restrict to these types (default: all valid types)
        output_format: For quiz/flashcards: json|markdown|html
        slide_deck_format: For slide decks: pdf (default) or pptx
        skip_existing: Skip artifacts whose target file already exists,
            making repeated runs incremental
        progress_factory: Called with (artifact_type, filename) before each
            streaming download; may return a (current, total) progress callback

    Returns:
        DownloadAllResult with per-artifact outcomes and summary counts

    Raises:
        ValidationError: If a requested type or format is invalid
        ServiceError: If the artifact list cannot be retrieved
    """
    requested = tuple(artifact_types) if artifact_types else VALID_ARTIFACT_TYPES
    for artifact_type in requested:
        validate_artifact_type(artifact_type)
    validate_output_format(output_format)
    validate_slide_deck_format(slide_deck_format)

    try:
        notebook_title = get_notebook(client, notebook_id).get("title") or notebook_id
    except Exception:
        notebook_title = notebook_id

    status = get_studio_status(client, notebook_id)

    dir_name = (
        notebook_dir_name
        if notebook_dir_name
        else sanitize_filename(notebook_title, fallback=notebook_id)
    )
    base_dir = Path(validate_output_path(output_dir, enforce_root=enforce_root))
    notebook_dir = base_dir / dir_name
    validate_output_path(str(notebook_dir), enforce_root=enforce_root)
    notebook_dir.mkdir(parents=True, exist_ok=True)

    items: list[DownloadAllItem] = []
    skipped: list[SkippedArtifact] = []
    used_names: set[str] = set()

    for artifact in status["artifacts"]:
        artifact_type = artifact.get("type") or "unknown"
        title = artifact.get("title") or ""
        artifact_id = artifact.get("artifact_id")

        if artifact_type not in VALID_ARTIFACT_TYPES:
            skipped.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "reason": f"unsupported artifact type '{artifact_type}'",
                }
            )
            continue
        if artifact_type not in requested:
            skipped.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "reason": "type not requested",
                }
            )
            continue
        if artifact.get("status") != "completed":
            skipped.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "reason": f"not completed (status: {artifact.get('status') or 'unknown'})",
                }
            )
            continue

        download_filename = artifact.get("download_filename")
        if artifact_type in ("data_table_xlsx", "file") and isinstance(download_filename, str):
            filename = sanitize_filename(Path(download_filename).name, fallback=artifact_type)
            if artifact_type == "data_table_xlsx" and not filename.lower().endswith(".xlsx"):
                filename = f"{filename}.xlsx"
            suffix = Path(filename).suffix
            if suffix:
                stem = filename[: -len(suffix)]
                ext = suffix[1:]
            else:
                stem = filename
                ext = get_default_extension(artifact_type, output_format)
                filename = f"{stem}.{ext}"
        elif artifact_type == "slide_deck":
            ext = slide_deck_format
            stem = sanitize_filename(title, fallback=artifact_type)
            filename = f"{stem}.{ext}"
        else:
            ext = get_default_extension(artifact_type, output_format)
            stem = sanitize_filename(title, fallback=artifact_type)
            filename = f"{stem}.{ext}"
        counter = 2
        while filename.lower() in used_names:
            filename = f"{stem}_{counter}.{ext}"
            counter += 1
        used_names.add(filename.lower())
        output_path = str(notebook_dir / filename)

        if skip_existing and (notebook_dir / filename).exists():
            skipped.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "reason": "already downloaded",
                }
            )
            continue

        progress_callback = None
        if progress_factory is not None and artifact_type in STREAMING_TYPES:
            progress_callback = progress_factory(artifact_type, filename)

        try:
            staging = (
                tempfile.TemporaryDirectory(prefix=".nlm-download-", dir=notebook_dir)
                if skip_existing
                else nullcontext(None)
            )
            with staging as staging_dir:
                target = str(Path(staging_dir) / filename) if staging_dir else output_path
                result = await download_async(
                    client,
                    notebook_id,
                    artifact_type,
                    target,
                    artifact_id=artifact_id,
                    output_format=output_format,
                    progress_callback=progress_callback,
                    slide_deck_format=slide_deck_format,
                )
                if staging_dir:
                    # Publish only if no other writer has claimed the destination.
                    # Windows rename refuses an existing destination; POSIX link
                    # provides the equivalent atomic no-replace operation.
                    try:
                        if os.name == "nt":
                            os.rename(target, output_path)
                        else:
                            os.link(target, output_path)
                    except FileExistsError:
                        skipped.append(
                            {
                                "artifact_id": artifact_id,
                                "artifact_type": artifact_type,
                                "title": title,
                                "reason": "already downloaded",
                            }
                        )
                        continue
                    result["path"] = output_path
            items.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "path": result["path"],
                    "success": True,
                    "error": None,
                }
            )
        except ServiceError as e:
            items.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "path": output_path,
                    "success": False,
                    "error": e.user_message or str(e),
                }
            )
        except Exception as e:
            items.append(
                {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "path": output_path,
                    "success": False,
                    "error": str(e),
                }
            )

    downloaded = sum(1 for item in items if item["success"])
    return {
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "output_dir": str(notebook_dir),
        "items": items,
        "skipped": skipped,
        "total_artifacts": status["total"],
        "downloaded": downloaded,
        "failed": len(items) - downloaded,
    }


async def download_all_notebooks(
    client: NotebookLMClient,
    output_dir: str = ".",
    artifact_types: Sequence[str] | None = None,
    output_format: str = "json",
    slide_deck_format: str = "pdf",
    skip_existing: bool = False,
    progress_factory: Callable[[str, str], Callable[[int, int], None] | None] | None = None,
    on_notebook: Callable[[int, int, str], None] | None = None,
    *,
    enforce_root: bool = False,
) -> DownloadAllNotebooksResult:
    """Run download_all() over every notebook in the account.

    Each notebook gets its own subdirectory of ``output_dir``. A failure on
    one notebook (or one artifact) is recorded and does not stop the sweep.
    With ``skip_existing`` the sweep is incremental: artifacts whose target
    file already exists are not re-downloaded.

    Args:
        client: Authenticated NotebookLM client
        output_dir: Base directory for the per-notebook directories
        artifact_types: Restrict to these types (default: all valid types)
        output_format: For quiz/flashcards: json|markdown|html
        slide_deck_format: For slide decks: pdf (default) or pptx
        skip_existing: Skip artifacts whose target file already exists
        progress_factory: Passed through to download_all() for each notebook
        on_notebook: Called with (index, total, title) before each notebook —
            a UX hook for progress narration

    Returns:
        DownloadAllNotebooksResult with per-notebook outcomes and totals

    Raises:
        ValidationError: If a requested type or format is invalid
        ServiceError: If the notebook list cannot be retrieved
    """
    requested = tuple(artifact_types) if artifact_types else VALID_ARTIFACT_TYPES
    for artifact_type in requested:
        validate_artifact_type(artifact_type)
    validate_output_format(output_format)
    validate_slide_deck_format(slide_deck_format)

    notebooks = list_notebooks(client)["notebooks"]

    sweep: list[NotebookSweepItem] = []
    total_downloaded = total_failed = 0
    used_dirs: set[str] = set()

    for index, notebook in enumerate(notebooks, 1):
        title = notebook.get("title") or notebook["id"]

        base_dir = sanitize_filename(title, fallback=notebook["id"])
        dir_name = base_dir
        counter = 2
        while dir_name.lower() in used_dirs:
            dir_name = f"{base_dir}_{counter}"
            counter += 1
        used_dirs.add(dir_name.lower())

        if on_notebook is not None:
            on_notebook(index, len(notebooks), title)
        try:
            result = await download_all(
                client,
                notebook["id"],
                output_dir,
                artifact_types=artifact_types,
                output_format=output_format,
                slide_deck_format=slide_deck_format,
                skip_existing=skip_existing,
                progress_factory=progress_factory,
                notebook_dir_name=dir_name,
                enforce_root=enforce_root,
            )
        except ServiceError as e:
            sweep.append(
                {
                    "notebook_id": notebook["id"],
                    "notebook_title": title,
                    "output_dir": None,
                    "downloaded": 0,
                    "failed": 0,
                    "skipped": 0,
                    "error": e.user_message or str(e),
                }
            )
            continue
        except Exception as e:
            sweep.append(
                {
                    "notebook_id": notebook["id"],
                    "notebook_title": title,
                    "output_dir": None,
                    "downloaded": 0,
                    "failed": 0,
                    "skipped": 0,
                    "error": str(e),
                }
            )
            continue

        total_downloaded += result["downloaded"]
        total_failed += result["failed"]
        sweep.append(
            {
                "notebook_id": result["notebook_id"],
                "notebook_title": result["notebook_title"],
                "output_dir": result["output_dir"],
                "downloaded": result["downloaded"],
                "failed": result["failed"],
                "skipped": len(result["skipped"]),
                "error": None,
            }
        )

    return {
        "output_dir": validate_output_path(output_dir, enforce_root=enforce_root),
        "notebooks": sweep,
        "total_notebooks": len(notebooks),
        "downloaded": total_downloaded,
        "failed": total_failed,
        "errored_notebooks": sum(1 for item in sweep if item["error"]),
    }


def _dispatch_sync(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_type: str,
    output_path: str,
    artifact_id: str | None,
    output_format: str,
) -> str:
    """Route to the correct synchronous client method."""
    if artifact_type in ("report", "interactive_report"):
        return client.download_report(notebook_id, output_path, artifact_id)
    elif artifact_type == "mind_map":
        return client.download_mind_map(notebook_id, output_path, artifact_id)
    elif artifact_type in ("data_table", "data_table_xlsx"):
        return client.download_data_table(notebook_id, output_path, artifact_id)
    elif artifact_type == "file":
        return client.download_file(notebook_id, output_path, artifact_id)
    else:
        raise ValidationError(
            f"Artifact type '{artifact_type}' requires async download. "
            f"Use download_async() instead.",
        )


async def _resolve_download_result(result: str | Awaitable[str]) -> str:
    """Await async download results but also accept synchronous implementations."""
    if inspect.isawaitable(result):
        return await result
    return result


def _get_download_method(
    client: NotebookLMClient,
    async_name: str,
    sync_name: str,
) -> Callable[..., Any]:
    """Prefer explicit async client aliases when the concrete client class provides them."""
    if getattr(type(client), async_name, None) is not None:
        return cast(Callable[..., Any], getattr(client, async_name))
    return cast(Callable[..., Any], getattr(client, sync_name))


async def _dispatch_async(
    client: NotebookLMClient,
    notebook_id: str,
    artifact_type: str,
    output_path: str,
    artifact_id: str | None,
    output_format: str,
    progress_callback: Callable[[int, int], None] | None,
    slide_deck_format: str = "pdf",
) -> str:
    """Route to the correct async client method."""
    # Non-streaming types (sync client methods callable from async context)
    if artifact_type in ("report", "interactive_report"):
        return await _resolve_download_result(
            client.download_report(notebook_id, output_path, artifact_id)
        )
    elif artifact_type == "mind_map":
        return await _resolve_download_result(
            client.download_mind_map(notebook_id, output_path, artifact_id)
        )
    elif artifact_type in ("data_table", "data_table_xlsx"):
        return await _resolve_download_result(
            client.download_data_table(notebook_id, output_path, artifact_id)
        )
    elif artifact_type == "file":
        return await _resolve_download_result(
            client.download_file(notebook_id, output_path, artifact_id)
        )
    # Streaming types (async client methods)
    elif artifact_type == "audio":
        download_audio = _get_download_method(client, "download_audio_async", "download_audio")
        return await _resolve_download_result(
            download_audio(
                notebook_id,
                output_path,
                artifact_id,
                progress_callback=progress_callback,
            )
        )
    elif artifact_type == "video":
        download_video = _get_download_method(client, "download_video_async", "download_video")
        return await _resolve_download_result(
            download_video(
                notebook_id,
                output_path,
                artifact_id,
                progress_callback=progress_callback,
            )
        )
    elif artifact_type == "slide_deck":
        download_slide_deck = _get_download_method(
            client, "download_slide_deck_async", "download_slide_deck"
        )
        return await _resolve_download_result(
            download_slide_deck(
                notebook_id,
                output_path,
                artifact_id,
                progress_callback=progress_callback,
                file_format=slide_deck_format,
            )
        )
    elif artifact_type == "infographic":
        download_infographic = _get_download_method(
            client, "download_infographic_async", "download_infographic"
        )
        return await _resolve_download_result(
            download_infographic(
                notebook_id,
                output_path,
                artifact_id,
                progress_callback=progress_callback,
            )
        )
    elif artifact_type == "quiz":
        download_quiz = _get_download_method(client, "download_quiz_async", "download_quiz")
        return await _resolve_download_result(
            download_quiz(
                notebook_id,
                output_path,
                artifact_id,
                output_format,
            )
        )
    elif artifact_type == "flashcards":
        download_flashcards = _get_download_method(
            client, "download_flashcards_async", "download_flashcards"
        )
        return await _resolve_download_result(
            download_flashcards(
                notebook_id,
                output_path,
                artifact_id,
                output_format,
            )
        )
    else:
        raise ValidationError(
            f"Artifact type '{artifact_type}' is not supported for async download.",
        )
