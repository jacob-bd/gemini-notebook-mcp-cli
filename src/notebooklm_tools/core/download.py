#!/usr/bin/env python3
"""Download operations mixin for NotebookLM client."""

import asyncio
import csv
import html as html_module
import json
import os
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import BaseClient, logger
from .errors import (
    ArtifactDownloadError,
    ArtifactNotFoundError,
    ArtifactNotReadyError,
    ArtifactParseError,
)
from .errors import (
    ClientAuthenticationError as AuthenticationError,
)
from .studio import render_interactive_report_markdown
from .utils import is_mind_map_json


def _create_download_temp_path(output_file: Path) -> Path:
    """Reserve a unique same-directory temp file for one download transfer."""
    # Not tempfile.mkstemp: it forces 0600, which the final file would inherit.
    # O_EXCL still guarantees a unique file; 0o666 lets the umask decide the mode.
    temp_path = output_file.parent / f".nlm-download-{uuid.uuid4().hex}.tmp"
    os.close(os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))
    return temp_path


class DownloadMixin(BaseClient):
    """Mixin for artifact download operations.

    This mixin provides methods for downloading various artifact types:
    - Audio (MP4/MP3)
    - Video (MP4)
    - Infographic (PNG)
    - Slide Deck (PDF)
    - Report (Markdown)
    - Mind Map (JSON)
    - Data Table (CSV)
    - Quiz (JSON/Markdown/HTML)
    - Flashcards (JSON/Markdown/HTML)
    """

    _AUDIO_DOWNLOAD_RETRY_DELAYS = (5, 10, 20, 30, 45, 60, 60)
    # Keep video retries brief; MCP's optional wait loop can keep polling after
    # these attempts, while a one-shot CLI download stays responsive.
    _VIDEO_DOWNLOAD_RETRY_DELAYS = (5, 10, 20)
    _GOOGLE_MEDIA_DOWNLOAD_HOSTS = {
        "drum.usercontent.google.com",
        "lh3.googleusercontent.com",
        "lh3.google.com",
    }

    # =========================================================================
    # Core Download Infrastructure
    # =========================================================================

    def _audio_artifact_has_media_urls(self, artifact: list[Any]) -> bool:
        """Return True when an audio artifact exposes media URLs."""
        if len(artifact) <= 6:
            return False

        metadata = artifact[6]
        if not isinstance(metadata, list) or len(metadata) <= 5:
            return False

        media_list = metadata[5]
        if not isinstance(media_list, list):
            return False

        return any(
            isinstance(item, list)
            and len(item) > 0
            and isinstance(item[0], str)
            and item[0].startswith("http")
            for item in media_list
        )

    def _is_audio_artifact_ready(self, artifact: list[Any]) -> bool:
        """Treat verified ready audio payloads as downloadable.

        Audio artifacts have been observed with status code ``2`` while already
        exposing media URLs in their metadata. Keep support narrow to that
        verified shape; everything else still requires the explicit completed
        code.
        """
        if not isinstance(artifact, list) or len(artifact) <= 4:
            return False
        if artifact[2] != self.STUDIO_TYPE_AUDIO:
            return False

        status_code = artifact[4]
        return status_code == 3 or (
            status_code == 2 and self._audio_artifact_has_media_urls(artifact)
        )

    def _is_transient_audio_media_404(self, url: str, error: ArtifactDownloadError) -> bool:
        cause = error.__cause__
        if not isinstance(cause, httpx.HTTPStatusError):
            return False
        if cause.response.status_code != 404:
            return False

        original_host = urlparse(url).hostname
        final_url = urlparse(str(cause.response.url))
        return (
            original_host in self._GOOGLE_MEDIA_DOWNLOAD_HOSTS
            and final_url.hostname in self._GOOGLE_MEDIA_DOWNLOAD_HOSTS
            and final_url.path.startswith("/rd-notebooklm/")
        )

    def _is_transient_video_media_404(self, url: str, error: ArtifactDownloadError) -> bool:
        cause = error.__cause__
        if not isinstance(cause, httpx.HTTPStatusError) or cause.response.status_code != 404:
            return False

        original = urlparse(url)
        final = urlparse(str(cause.response.url))
        return (
            original.hostname in self._GOOGLE_MEDIA_DOWNLOAD_HOSTS
            and original.path.startswith("/notebooklm/")
            and final.hostname in self._GOOGLE_MEDIA_DOWNLOAD_HOSTS
            and final.path.startswith(("/notebooklm/", "/rd-notebooklm/"))
        )

    @staticmethod
    def _is_html_login_redirect(first_chunk: bytes) -> bool:
        """Return True when an HTML response chunk looks like a Google login redirect."""
        lower = first_chunk.lower()
        return b"<!doctype html>" in lower or b"sign in" in lower

    async def _download_url(
        self,
        url: str,
        output_path: str,
        progress_callback: Callable[[int, int], None] | None = None,
        chunk_size: int = 65536,
    ) -> str:
        """Download content from a URL to a local file with streaming support.

        Features:
        - Streams file in chunks to minimize memory usage
        - Optional progress callback for UI integration
        - Per-chunk timeouts to detect stalled connections
        - Temp file usage to prevent corrupted partial downloads
        - Authentication error detection

        Args:
            url: The URL to download
            output_path: The local path to save the file
            progress_callback: Optional callback(bytes_downloaded, total_bytes)
            chunk_size: Size of chunks to read (default 64KB)

        Returns:
            The output path

        Raises:
            ArtifactDownloadError: If download fails
            AuthenticationError: If auth redirect detected
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Build headers with auth cookies
        base_headers = getattr(
            self,
            "_PAGE_FETCH_HEADERS",
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        # Mirror Chrome's window.open() from notebooklm.google.com to a cross-domain
        # artifact host (lh3.googleusercontent.com / lh3.google.com). The audio CDN
        # treats "Sec-Fetch-Site: none" as an address-bar navigation and returns 403;
        # the UI's Download button succeeds because window.open() makes Chrome stamp
        # the request with "Sec-Fetch-Site: cross-site" + Referer=notebooklm.google.com.
        headers = {
            **base_headers,
            "Referer": f"{self._get_base_url()}/",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
        }

        # Use httpx.Cookies for proper cross-domain redirect handling
        cookies = self._get_httpx_cookies()

        # Drop OSID cookies before issuing the download request.
        # OSID is scoped to notebooklm.google.com; when it leaks onto download
        # hosts (e.g. lh3.googleusercontent.com) Google treats the request as
        # an invalid session and redirects to ServiceLogin, breaking downloads.
        for domain in (".google.com", ".googleusercontent.com"):
            cookies.delete("OSID", domain=domain)
            cookies.delete("__Secure-OSID", domain=domain)

        # Per-chunk timeouts: 10s connect, 30s per chunk read/write
        # This allows large files to download without timeout while detecting stalls
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
        temp_file = _create_download_temp_path(output_file)

        try:
            async with (
                httpx.AsyncClient(
                    cookies=cookies, headers=headers, follow_redirects=True, timeout=timeout
                ) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()

                # Get total size if available
                content_length = response.headers.get("content-length")
                total_bytes = int(content_length) if content_length else 0

                # Check for auth redirect before starting download
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    # Read first chunk to check for login page
                    first_chunk = b""
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        first_chunk = chunk
                        break

                    if self._is_html_login_redirect(first_chunk):
                        raise AuthenticationError(
                            "Download failed: Redirected to login page. "
                            "Run 'nlm login' to refresh credentials."
                        )

                    # Not an auth error - write first chunk and continue
                    with open(temp_file, "wb") as f:
                        f.write(first_chunk)
                        bytes_downloaded = len(first_chunk)

                        if progress_callback:
                            progress_callback(bytes_downloaded, total_bytes)

                        # Continue streaming rest of file
                        async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                            f.write(chunk)
                            bytes_downloaded += len(chunk)

                            if progress_callback:
                                progress_callback(bytes_downloaded, total_bytes)
                else:
                    # Binary content - stream directly
                    bytes_downloaded = 0
                    with open(temp_file, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                            f.write(chunk)
                            bytes_downloaded += len(chunk)

                            if progress_callback:
                                progress_callback(bytes_downloaded, total_bytes)

            # Move temp file to final location only on success
            os.replace(temp_file, output_file)
            return str(output_file)

        except AuthenticationError:
            raise
        except httpx.HTTPError as e:
            # Clean up temp file on failure
            if temp_file.exists():
                temp_file.unlink()
            raise ArtifactDownloadError(
                "file", details=f"HTTP error downloading from {url[:50]}...: {e}"
            ) from e
        except Exception as e:
            # Clean up temp file on failure
            if temp_file.exists():
                temp_file.unlink()
            raise ArtifactDownloadError(
                "file", details=f"Failed to download from {url[:50]}...: {str(e)}"
            ) from e
        finally:
            # Also covers cancellation/Ctrl-C, which skip the except blocks above.
            temp_file.unlink(missing_ok=True)

    def _download_url_sync(self, url: str, output_path: str) -> str:
        """Stream a binary artifact URL synchronously to a local file."""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        base_headers = getattr(
            self,
            "_PAGE_FETCH_HEADERS",
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        headers = {
            **base_headers,
            "Referer": f"{self._get_base_url()}/",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
        }
        cookies = self._get_httpx_cookies()
        for domain in (".google.com", ".googleusercontent.com"):
            cookies.delete("OSID", domain=domain)
            cookies.delete("__Secure-OSID", domain=domain)

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
        temp_file = _create_download_temp_path(output_file)
        try:
            with (
                httpx.Client(
                    cookies=cookies, headers=headers, follow_redirects=True, timeout=timeout
                ) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    chunks = response.iter_bytes(chunk_size=8192)
                    first_chunk = next(chunks, b"")
                    if self._is_html_login_redirect(first_chunk):
                        raise AuthenticationError(
                            "Download failed: Redirected to login page. "
                            "Run 'nlm login' to refresh credentials."
                        )
                    with open(temp_file, "wb") as output:
                        if first_chunk:
                            output.write(first_chunk)
                        for chunk in chunks:
                            output.write(chunk)
                else:
                    with open(temp_file, "wb") as output:
                        for chunk in response.iter_bytes(chunk_size=65536):
                            output.write(chunk)

            os.replace(temp_file, output_file)
            return str(output_file)
        except AuthenticationError:
            raise
        except httpx.HTTPError as e:
            if temp_file.exists():
                temp_file.unlink()
            raise ArtifactDownloadError(
                "file", details=f"HTTP error downloading from {url[:50]}...: {e}"
            ) from e
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise ArtifactDownloadError(
                "file", details=f"Failed to download from {url[:50]}...: {e}"
            ) from e
        finally:
            temp_file.unlink(missing_ok=True)

    def _list_raw(self, notebook_id: str) -> list[Any]:
        """Get raw artifact list for parsing download URLs."""
        # Poll params: [[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']
        params = [[2], notebook_id, 'NOT artifact.status = "ARTIFACT_STATUS_SUGGESTED"']

        result = self._call_rpc(self.RPC_POLL_STUDIO, params, path=f"/notebook/{notebook_id}")

        if result and isinstance(result, list) and len(result) > 0:
            # Response is an array of artifacts, possibly wrapped
            return result[0] if isinstance(result[0], list) else result
        return []

    # =========================================================================
    # Binary Artifact Downloads (Audio, Video, Infographic, Slide Deck)
    # =========================================================================

    async def download_audio(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        """Download an Audio Overview to a file.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the audio file (MP4/MP3).
            artifact_id: Specific artifact ID, or uses first completed audio.
            progress_callback: Optional callback(bytes_downloaded, total_bytes).

        Returns:
            The output path.
        """
        try:

            def select_target() -> list[Any]:
                artifacts = self._list_raw(notebook_id)

                # Filter for ready audio artifacts. Some completed audio payloads use
                # status code 2 while already exposing media URLs.
                candidates = [a for a in artifacts if self._is_audio_artifact_ready(a)]

                if not candidates:
                    raise ArtifactNotReadyError("audio")

                if artifact_id:
                    target = next((a for a in candidates if a[0] == artifact_id), None)
                    if not target:
                        raise ArtifactNotReadyError("audio", artifact_id)
                    return target
                return candidates[0]

            def select_url(target: list[Any]) -> str:
                # Extract URL from metadata[6][5]
                metadata = target[6]
                if not isinstance(metadata, list) or len(metadata) <= 5:
                    raise ArtifactParseError("audio", details="Invalid audio metadata structure")

                media_list = metadata[5]
                if not isinstance(media_list, list) or len(media_list) == 0:
                    raise ArtifactParseError("audio", details="No media URLs found in metadata")

                # Look for a downloadable audio/mp4 URL.
                # Google's media list contains multiple entries:
                #   =m140-dv  (priority 4, "download variant" — fast CDN via drum.usercontent.google.com)
                #   =m140     (priority 1, streaming transcode — slow CDN via googlevideo.com)
                # Prefer the "-dv" variant which is the intended download endpoint.
                url = None
                for item in media_list:
                    if isinstance(item, list) and len(item) > 2 and item[2] == "audio/mp4":
                        candidate = item[0]
                        if isinstance(candidate, str) and candidate.endswith("-dv"):
                            url = candidate
                            break

                # Fallback: any audio/mp4 URL
                if not url:
                    for item in media_list:
                        if isinstance(item, list) and len(item) > 2 and item[2] == "audio/mp4":
                            url = item[0]
                            break

                # Last resort: first URL regardless of type
                if not url and len(media_list) > 0 and isinstance(media_list[0], list):
                    url = media_list[0][0]

                if not url:
                    raise ArtifactDownloadError("audio", details="No download URL found")
                return url

            target = select_target()
            url = select_url(target)

            for attempt in range(len(self._AUDIO_DOWNLOAD_RETRY_DELAYS) + 1):
                try:
                    return await self._download_url(url, output_path, progress_callback)
                except ArtifactDownloadError as e:
                    if not self._is_transient_audio_media_404(url, e):
                        raise
                    if attempt == len(self._AUDIO_DOWNLOAD_RETRY_DELAYS):
                        raise ArtifactDownloadError(
                            "audio",
                            details="media download URL is still propagating; retry in a few minutes",
                        ) from e

                    delay = self._AUDIO_DOWNLOAD_RETRY_DELAYS[attempt]
                    logger.warning(
                        f"Audio media URL returned 404 while propagating; "
                        f"retrying in {delay:.0f}s..."
                    )
                    await asyncio.sleep(delay)
                    target = select_target()
                    url = select_url(target)

            raise ArtifactDownloadError("audio", details="No download URL found")

        except (IndexError, TypeError, AttributeError) as e:
            raise ArtifactParseError("audio", details=str(e)) from e

    async def download_video(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        """Download a Video Overview to a file.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the video file (MP4).
            artifact_id: Specific artifact ID, or uses first completed video.
            progress_callback: Optional callback(bytes_downloaded, total_bytes).

        Returns:
            The output path.
        """
        try:

            def select_url() -> str:
                artifacts = self._list_raw(notebook_id)
                candidates = [
                    a
                    for a in artifacts
                    if isinstance(a, list)
                    and len(a) > 4
                    and a[2] == self.STUDIO_TYPE_VIDEO
                    and a[4] == 3
                ]
                if not candidates:
                    raise ArtifactNotReadyError("video")
                target = (
                    next((a for a in candidates if a[0] == artifact_id), None)
                    if artifact_id
                    else candidates[0]
                )
                if target is None:
                    raise ArtifactNotReadyError("video", artifact_id)

                metadata = target[8]
                if not isinstance(metadata, list):
                    raise ArtifactParseError("video", details="Invalid metadata structure")

                media_list = next(
                    (
                        item
                        for item in metadata
                        if isinstance(item, list)
                        and item
                        and isinstance(item[0], list)
                        and item[0]
                        and isinstance(item[0][0], str)
                        and item[0][0].startswith("http")
                    ),
                    None,
                )
                if not media_list:
                    raise ArtifactDownloadError("video", details="No media URLs found in metadata")

                # Prefer the video/mp4 download variant (priority 4).
                urls = [
                    item
                    for item in media_list
                    if isinstance(item, list) and len(item) > 2 and item[2] == "video/mp4"
                ]
                preferred = next((item for item in urls if len(item) > 1 and item[1] == 4), None)
                fallback = media_list[0] if isinstance(media_list[0], list) else None
                selected = preferred or (urls[0] if urls else fallback)
                url = selected[0] if selected and isinstance(selected[0], str) else None
                if not url:
                    raise ArtifactDownloadError("video", details="No download URL found")
                return url

            url = select_url()
            for attempt in range(len(self._VIDEO_DOWNLOAD_RETRY_DELAYS) + 1):
                try:
                    return await self._download_url(url, output_path, progress_callback)
                except ArtifactDownloadError as e:
                    if not self._is_transient_video_media_404(url, e):
                        raise
                    if attempt == len(self._VIDEO_DOWNLOAD_RETRY_DELAYS):
                        raise ArtifactDownloadError(
                            "video",
                            details="media download URL is still propagating; retry in a few minutes",
                        ) from e
                    delay = self._VIDEO_DOWNLOAD_RETRY_DELAYS[attempt]
                    logger.warning(
                        "Video media URL returned 404 while propagating; retrying in %.0fs...",
                        delay,
                    )
                    await asyncio.sleep(delay)
                    url = select_url()

            raise ArtifactDownloadError("video", details="No download URL found")

        except (IndexError, TypeError, AttributeError) as e:
            raise ArtifactParseError("video", details=str(e)) from e

    async def download_infographic(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        """Download an Infographic to a file.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the PNG file.
            artifact_id: Specific artifact ID, or uses first completed infographic.
            progress_callback: Optional callback(bytes_downloaded, total_bytes).

        Returns:
            The output path.
        """
        artifacts = self._list_raw(notebook_id)

        # Filter for completed infographics (Type 7, Status 3)
        candidates = []
        for a in artifacts:
            if isinstance(a, list) and len(a) > 5:  # noqa: SIM102
                if a[2] == self.STUDIO_TYPE_INFOGRAPHIC and a[4] == 3:
                    candidates.append(a)

        if not candidates:
            raise ArtifactNotReadyError("infographic")

        target = None
        if artifact_id:
            target = next((a for a in candidates if a[0] == artifact_id), None)
            if not target:
                raise ArtifactNotReadyError("infographic", artifact_id)
        else:
            target = candidates[0]

        # Extract URL from target[14][2][0][1][0] (lh3.googleusercontent.com)
        try:
            if len(target) <= 14 or target[14] is None:
                raise ArtifactParseError("infographic", details="Invalid metadata structure")

            metadata = target[14]
            if not isinstance(metadata, list) or len(metadata) < 3:
                raise ArtifactParseError("infographic", details="No media data in metadata")

            media_data = metadata[2]
            if not isinstance(media_data, list) or len(media_data) == 0:
                raise ArtifactParseError("infographic", details="No media items found")

            # Navigate: media_data[0][1][0] to get URL
            media_item = media_data[0]
            if not isinstance(media_item, list) or len(media_item) < 2:
                raise ArtifactParseError("infographic", details="Invalid media item structure")

            url_data = media_item[1]
            if not isinstance(url_data, list) or len(url_data) == 0:
                raise ArtifactParseError("infographic", details="No URL data found")

            url = url_data[0]
            if not url or not isinstance(url, str):
                raise ArtifactDownloadError("infographic", details="No download URL found")

            return await self._download_url(url, output_path, progress_callback)

        except (IndexError, TypeError, AttributeError) as e:
            raise ArtifactParseError("infographic", details=str(e)) from e

    async def download_slide_deck(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        file_format: str = "pdf",
    ) -> str:
        """Download a Slide Deck to a file (PDF or PPTX).

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the file.
            artifact_id: Specific artifact ID, or uses first completed slide deck.
            progress_callback: Optional callback(bytes_downloaded, total_bytes).
            file_format: "pdf" (default) or "pptx".

        Returns:
            The output path.
        """
        artifacts = self._list_raw(notebook_id)

        # Filter for completed slide decks (Type 8, Status 3)
        candidates = []
        for a in artifacts:
            if isinstance(a, list) and len(a) > 5:  # noqa: SIM102
                if a[2] == self.STUDIO_TYPE_SLIDE_DECK and a[4] == 3:
                    candidates.append(a)

        if not candidates:
            raise ArtifactNotReadyError("slide_deck")

        target = None
        if artifact_id:
            target = next((a for a in candidates if a[0] == artifact_id), None)
            if not target:
                raise ArtifactNotReadyError("slide_deck", artifact_id)
        else:
            target = candidates[0]

        # Extract URL from target[16]: index 3 = PDF, index 4 = PPTX
        try:
            if len(target) <= 16 or target[16] is None:
                raise ArtifactParseError("slide_deck", details="Invalid metadata structure")

            metadata = target[16]
            if file_format == "pptx":
                if not isinstance(metadata, list) or len(metadata) < 5:
                    raise ArtifactParseError("slide_deck", details="No PPTX URL found in metadata")
                url = metadata[4]
                if not url or not isinstance(url, str):
                    raise ArtifactDownloadError("slide_deck", details="No PPTX download URL found")
            else:
                if not isinstance(metadata, list) or len(metadata) < 4:
                    raise ArtifactParseError("slide_deck", details="No PDF URL found in metadata")
                url = metadata[3]
                if not url or not isinstance(url, str):
                    raise ArtifactDownloadError("slide_deck", details="No PDF download URL found")

            return await self._download_url(url, output_path, progress_callback)

        except (IndexError, TypeError, AttributeError) as e:
            raise ArtifactParseError("slide_deck", details=str(e)) from e

    # =========================================================================
    # Text Artifact Downloads (Report, Mind Map, Data Table)
    # =========================================================================

    def download_report(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Download a report artifact as markdown.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the markdown file.
            artifact_id: Specific artifact ID, or uses first completed report.

        Returns:
            The output path where the file was saved.
        """
        artifacts = self._list_raw(notebook_id)

        # Filter for completed reports (classic type 2 and interactive type 11)
        candidates = []
        for a in artifacts:
            if isinstance(a, list) and len(a) > 7:  # noqa: SIM102
                if (
                    a[2] in (self.STUDIO_TYPE_REPORT, self.STUDIO_TYPE_INTERACTIVE_REPORT)
                    and a[4] == 3
                ):
                    candidates.append(a)

        if not candidates:
            raise ArtifactNotReadyError("report")

        target = None
        if artifact_id:
            target = next((a for a in candidates if a[0] == artifact_id), None)
            if not target:
                raise ArtifactNotReadyError("report", artifact_id)
        else:
            target = candidates[0]

        try:
            if target[2] == self.STUDIO_TYPE_INTERACTIVE_REPORT:
                # Interactive reports render from their structured document
                # (index 34). Prepend the artifact title as a Markdown H1; the
                # document itself starts at H2 level.
                markdown_content = render_interactive_report_markdown(target)
                if not markdown_content:
                    raise ArtifactParseError(
                        "report", details="Interactive report has no document yet"
                    )
                title = target[1] if len(target) > 1 and isinstance(target[1], str) else ""
                if title:
                    markdown_content = f"# {title}\n\n{markdown_content}"

                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(markdown_content, encoding="utf-8")
                return str(output)

            # Report content is in index 7
            content_wrapper = target[7]
            markdown_content = ""

            if isinstance(content_wrapper, list) and len(content_wrapper) > 0:
                markdown_content = content_wrapper[0]
            elif isinstance(content_wrapper, str):
                markdown_content = content_wrapper

            if not isinstance(markdown_content, str):
                raise ArtifactParseError("report", details="Invalid content structure")

            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(markdown_content, encoding="utf-8")
            return str(output)

        except (IndexError, TypeError, AttributeError) as e:
            raise ArtifactParseError("report", details=str(e)) from e

    def download_mind_map(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Download a mind map as JSON.

        Mind maps are stored in the notes system, not the regular artifacts list.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the JSON file.
            artifact_id: Specific mind map ID (note ID), or uses first available.

        Returns:
            The output path where the file was saved.
        """
        # Mind maps are retrieved via list_mind_maps RPC
        params = [notebook_id]
        result = self._call_rpc(self.RPC_LIST_MIND_MAPS, params, f"/notebook/{notebook_id}")

        mind_maps = []
        if result and isinstance(result, list) and len(result) > 0:  # noqa: SIM102
            if isinstance(result[0], list):
                mind_maps = result[0]

        # The notes store holds both regular notes (prose content) and mind
        # maps (JSON content) — keep only real mind maps so an unqualified
        # download can't pick a note and a note ID reports "not found".
        mind_maps = [
            mm
            for mm in mind_maps
            if isinstance(mm, list)
            and len(mm) > 1
            and isinstance(mm[1], list)
            and len(mm[1]) > 1
            and is_mind_map_json(mm[1][1])
        ]

        target = None
        if artifact_id:
            target = next(
                (mm for mm in mind_maps if isinstance(mm, list) and mm[0] == artifact_id), None
            )
        elif mind_maps:
            target = mind_maps[0]

        if target is None:
            # Newer mind maps are stored as type-4 studio artifacts (format
            # code 4) rather than in the notes store — fall back to those.
            return self._download_studio_mind_map(notebook_id, output_path, artifact_id)

        try:
            # Mind map JSON is stringified in target[1][1]
            if len(target) > 1 and isinstance(target[1], list) and len(target[1]) > 1:
                json_string = target[1][1]
                if isinstance(json_string, str):
                    json_data = json.loads(json_string)

                    output = Path(output_path)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(
                        json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8"
                    )
                    return str(output)

            raise ArtifactParseError("mind_map", details="Invalid structure")

        except (IndexError, TypeError, json.JSONDecodeError, AttributeError) as e:
            raise ArtifactParseError("mind_map", details=str(e)) from e

    def _download_studio_mind_map(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Download a studio-side mind map (type-4 artifact, format code 4).

        The mind map JSON ({"name": ..., "children": [...]}) is embedded in
        the artifact's interactive HTML as data-app-data.
        """
        artifacts = self._list_raw(notebook_id)
        candidates = [
            a
            for a in artifacts
            if isinstance(a, list)
            and len(a) > 4
            and a[2] == self.STUDIO_TYPE_FLASHCARDS
            and a[4] == 3
            and self._interactive_format_code(a) == 4
        ]

        if artifact_id:
            target = next((a for a in candidates if a[0] == artifact_id), None)
            if target is None:
                raise ArtifactNotFoundError(artifact_id, artifact_type="mind_map")
        else:
            if not candidates:
                raise ArtifactNotReadyError("mind_map")
            target = candidates[0]

        html_content = self._get_artifact_content(notebook_id, target[0])
        if not html_content:
            raise ArtifactDownloadError("mind_map", details="Failed to fetch HTML content from API")

        try:
            app_data = self._extract_app_data(html_content)
        except ArtifactParseError:
            raise
        except (ValueError, json.JSONDecodeError) as e:
            raise ArtifactParseError("mind_map", details=str(e)) from e

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(app_data, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"Downloaded mind map to {output}")
        return str(output)

    @staticmethod
    def _extract_cell_text(cell: Any, _depth: int = 0) -> str:
        """Recursively extract text from a nested data table cell structure.

        Data table cells have deeply nested arrays with position markers (integers)
        and text content (strings). This function traverses the structure and
        concatenates all text fragments found.

        Features:
        - Depth tracking to prevent infinite recursion (max 100 levels)
        - Handles None values gracefully
        - Strips whitespace from extracted text
        - Type validation at each level

        Args:
            cell: The cell data structure (can be str, int, list, or other)
            _depth: Internal recursion depth counter for safety

        Returns:
            Extracted text string, stripped of leading/trailing whitespace
        """
        # Safety: prevent infinite recursion
        if _depth > 100:
            return ""

        # Handle different types
        if cell is None:
            return ""
        if isinstance(cell, str):
            return cell.strip()
        if isinstance(cell, (int, float)):
            return ""  # Position markers are numeric
        if isinstance(cell, list):
            # Recursively extract from all list items
            parts = []
            for item in cell:
                text = DownloadMixin._extract_cell_text(item, _depth + 1)
                if text:
                    parts.append(text)
            return " ".join(parts) if parts else ""

        # Unknown type - convert to string as fallback
        return str(cell).strip()

    def _parse_data_table(
        self, raw_data: list, validate_columns: bool = True
    ) -> tuple[list[str], list[list[str]]]:
        """Parse rich-text data table into headers and rows.

        Features:
        - Validates structure at each navigation step with clear error messages
        - Optional column count validation across all rows
        - Handles missing/empty cells gracefully
        - Provides detailed error context for debugging

        Structure: raw_data[0][0][0][0][4][2] contains the rows array where:
        - [0][0][0][0] navigates through wrapper layers
        - [4] contains the table content section [type, flags, rows_array]
        - [2] is the actual rows array

        Each row: [start_pos, end_pos, [cell1, cell2, ...]]
        Each cell: deeply nested with position markers mixed with text

        Args:
            raw_data: The raw data table metadata from artifact[18]
            validate_columns: If True, ensures all rows have same column count as headers

        Returns:
            Tuple of (headers, rows) where:
            - headers: List of column names
            - rows: List of data rows (each row is a list matching header length)

        Raises:
            ArtifactParseError: With detailed context if parsing fails
        """
        # Validate and navigate structure with clear error messages
        try:
            if not isinstance(raw_data, list) or len(raw_data) == 0:
                raise ArtifactParseError(
                    "data_table",
                    details="Invalid raw_data: expected non-empty list at artifact[18]",
                )

            # Navigate: raw_data[0]
            layer1 = raw_data[0]
            if not isinstance(layer1, list) or len(layer1) == 0:
                raise ArtifactParseError(
                    "data_table",
                    details="Invalid structure at raw_data[0]: expected non-empty list",
                )

            # Navigate: [0][0]
            layer2 = layer1[0]
            if not isinstance(layer2, list) or len(layer2) == 0:
                raise ArtifactParseError(
                    "data_table",
                    details="Invalid structure at raw_data[0][0]: expected non-empty list",
                )

            # Navigate: [0][0][0]
            layer3 = layer2[0]
            if not isinstance(layer3, list) or len(layer3) == 0:
                raise ArtifactParseError(
                    "data_table",
                    details="Invalid structure at raw_data[0][0][0]: expected non-empty list",
                )

            # Navigate: [0][0][0][0]
            layer4 = layer3[0]
            if not isinstance(layer4, list) or len(layer4) < 5:
                raise ArtifactParseError(
                    "data_table",
                    details=f"Invalid structure at raw_data[0][0][0][0]: expected list with at least 5 elements, got {len(layer4) if isinstance(layer4, list) else type(layer4).__name__}",
                )

            # Navigate: [0][0][0][0][4] - table content section
            table_section = layer4[4]
            if not isinstance(table_section, list) or len(table_section) < 3:
                raise ArtifactParseError(
                    "data_table",
                    details=f"Invalid table section at raw_data[0][0][0][0][4]: expected list with at least 3 elements, got {len(table_section) if isinstance(table_section, list) else type(table_section).__name__}",
                )

            # Navigate: [0][0][0][0][4][2] - rows array
            rows_array = table_section[2]
            if not isinstance(rows_array, list):
                raise ArtifactParseError(
                    "data_table",
                    details=f"Invalid rows array at raw_data[0][0][0][0][4][2]: expected list, got {type(rows_array).__name__}",
                )

            if not rows_array:
                raise ArtifactParseError(
                    "data_table", details="Empty rows array - data table contains no data"
                )

        except IndexError as e:
            raise ArtifactParseError(
                "data_table",
                details=f"Structure navigation failed - table may be corrupted or in unexpected format: {e}",
            ) from e

        # Extract headers and rows
        headers: list[str] = []
        rows: list[list[str]] = []
        skipped_rows = 0

        for i, row_section in enumerate(rows_array):
            # Validate row format: [start_pos, end_pos, [cell_array]]
            if not isinstance(row_section, list):
                skipped_rows += 1
                continue

            if len(row_section) < 3:
                skipped_rows += 1
                continue

            cell_array = row_section[2]
            if not isinstance(cell_array, list):
                skipped_rows += 1
                continue

            # Extract text from each cell
            row_values = [self._extract_cell_text(cell) for cell in cell_array]

            # First row is headers
            if i == 0:
                headers = row_values
                if not headers or all(not h for h in headers):
                    raise ArtifactParseError(
                        "data_table",
                        details="First row (headers) is empty - table must have column headers",
                    )
            else:
                # Validate column count if requested
                if validate_columns and len(row_values) != len(headers):
                    # Pad or truncate to match header length
                    if len(row_values) < len(headers):
                        row_values.extend([""] * (len(headers) - len(row_values)))
                    else:
                        row_values = row_values[: len(headers)]

                rows.append(row_values)

        # Final validation
        if not headers:
            raise ArtifactParseError(
                "data_table", details="Failed to extract headers - first row may be malformed"
            )

        if not rows:
            raise ArtifactParseError(
                "data_table",
                details=f"No data rows extracted (skipped {skipped_rows} malformed rows)",
            )

        return headers, rows

    def download_data_table(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Download a data table as CSV or an XLSX export.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the CSV or XLSX file.
            artifact_id: Specific artifact ID, or uses first completed data table.

        Returns:
            The output path where the file was saved.
        """
        artifacts = self._list_raw(notebook_id)

        # Filter for completed data tables (Type 9) and XLSX exports (Type 10).
        candidates = []
        for a in artifacts:
            if isinstance(a, list) and len(a) > 4:  # noqa: SIM102
                if (
                    a[2] in (self.STUDIO_TYPE_DATA_TABLE, self.STUDIO_TYPE_DATA_TABLE_XLSX)
                    and a[4] == 3
                ):
                    candidates.append(a)

        if not candidates:
            raise ArtifactNotReadyError("data_table")

        target = None
        if artifact_id:
            target = next((a for a in candidates if a[0] == artifact_id), None)
            if not target:
                raise ArtifactNotReadyError("data_table", artifact_id)
        else:
            target = candidates[0]

        try:
            if target[2] == self.STUDIO_TYPE_DATA_TABLE_XLSX:
                # XLSX exports are already serialized binary files. The URL is
                # carried in [24] as [filename, mime, viewer_url, download_url].
                file_metadata = target[24]
                if (
                    not isinstance(file_metadata, list)
                    or len(file_metadata) <= 3
                    or not isinstance(file_metadata[3], str)
                    or not file_metadata[3]
                ):
                    raise ArtifactParseError(
                        "data_table",
                        details="Invalid XLSX download metadata at artifact[24]",
                    )
                return self._download_url_sync(file_metadata[3], output_path)

            # Data is at index 18
            raw_data = target[18]
            headers, rows = self._parse_data_table(raw_data)

            # Write to CSV
            output = Path(output_path)
            output.parent.mkdir(parents=True, exist_ok=True)

            with open(output, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                writer.writerows(rows)

            return str(output)

        except (IndexError, TypeError, AttributeError) as e:
            raise ArtifactParseError("data_table", details=str(e)) from e

    @staticmethod
    def _is_trusted_file_export_url(url: str) -> bool:
        """Return whether a Studio file URL is an HTTPS Google endpoint."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (
            host == "google.com"
            or host.endswith(".google.com")
            or host == "googleusercontent.com"
            or host.endswith(".googleusercontent.com")
            or host == "usercontent.google"
            or host.endswith(".usercontent.google")
        )

    def _resolve_file_viewer_url(self, viewer_url: str) -> tuple[str, str | None]:
        """Resolve a Drive viewer JSON envelope to its downloadable target."""
        if not self._is_trusted_file_export_url(viewer_url):
            raise ArtifactParseError(
                "file", details="Viewer URL must use HTTPS on a trusted Google host"
            )

        login_message = (
            "Download failed: Redirected to login page. Run 'nlm login' to refresh credentials."
        )

        def validate_viewer_request(request: httpx.Request) -> None:
            # HTTPX calls request hooks before sending the initial request and each redirect.
            if not self._is_trusted_file_export_url(str(request.url)):
                raise ArtifactParseError(
                    "file", details="Viewer redirects must use HTTPS on trusted Google hosts"
                )
            host = request.url.host
            if host == "accounts.google.com" or host.endswith(".accounts.google.com"):
                raise AuthenticationError(login_message)

        base_headers = getattr(
            self,
            "_PAGE_FETCH_HEADERS",
            {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"},
        )
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0)
        try:
            with httpx.Client(
                cookies=self._get_httpx_cookies(),
                headers=base_headers,
                follow_redirects=True,
                event_hooks={"request": [validate_viewer_request]},
                timeout=timeout,
            ) as client:
                response = client.get(viewer_url)
                if response.status_code == 401:
                    raise AuthenticationError(
                        "Download failed with HTTP 401. Run 'nlm login' to refresh credentials."
                    )
                if "text/html" in response.headers.get("content-type", "").lower():
                    html = response.content[:8192].lower()
                    if b"sign in to google" in html or b"accounts.google.com/servicelogin" in html:
                        raise AuthenticationError(login_message)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as e:
            raise ArtifactParseError("file", details=f"Invalid viewer response: {e}") from e

        if not isinstance(payload, dict):
            raise ArtifactParseError("file", details="Viewer response is not a JSON object")

        for format_name in ("pdf", "url", "downloadUrl", "download_url"):
            target_url = payload.get(format_name)
            if isinstance(target_url, str) and target_url:
                if not self._is_trusted_file_export_url(target_url):
                    raise ArtifactParseError(
                        "file",
                        details="Viewer target must use HTTPS on a trusted Google host",
                    )
                return target_url, "pdf" if format_name == "pdf" else None

        raise ArtifactParseError("file", details="Viewer response has no downloadable URL")

    def download_file(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
    ) -> str:
        """Download a generic type-10 Studio file export."""
        candidates = [
            artifact
            for artifact in self._list_raw(notebook_id)
            if isinstance(artifact, list)
            and len(artifact) > 24
            and artifact[2] == self.STUDIO_TYPE_DATA_TABLE_XLSX
            and artifact[4] == 3
        ]
        if not candidates:
            raise ArtifactNotReadyError("file")

        target = (
            next((artifact for artifact in candidates if artifact[0] == artifact_id), None)
            if artifact_id
            else candidates[0]
        )
        if target is None:
            raise ArtifactNotReadyError("file", artifact_id)

        metadata = target[24]
        if not isinstance(metadata, list) or len(metadata) < 3:
            raise ArtifactParseError("file", details="Invalid file metadata at artifact[24]")

        filename = metadata[0] if isinstance(metadata[0], str) else None
        direct_url = metadata[3] if len(metadata) > 3 else None
        resolved_format = None
        if isinstance(direct_url, str) and direct_url:
            target_url = direct_url
            if not self._is_trusted_file_export_url(target_url):
                raise ArtifactParseError(
                    "file", details="Download URL must use HTTPS on a trusted Google host"
                )
        else:
            viewer_url = metadata[2]
            if not isinstance(viewer_url, str) or not viewer_url:
                raise ArtifactParseError("file", details="File metadata has no viewer URL")
            target_url, resolved_format = self._resolve_file_viewer_url(viewer_url)

        output = Path(output_path)
        if resolved_format == "pdf" and (
            (filename and output.name == filename) or output.suffix.lower() == ".bin"
        ):
            output = output.with_suffix(".pdf")
        return self._download_url_sync(target_url, str(output))

    # =========================================================================
    # Interactive Artifact Downloads (Quiz, Flashcards)
    # =========================================================================

    @staticmethod
    def _interactive_format_code(artifact: Any) -> int | None:
        """Read the interactive subtype of a type-4 studio artifact.

        Type 4 (STUDIO_TYPE_FLASHCARDS) covers flashcards (1), quizzes (2),
        and mind maps (4); the code lives at artifact[9][1][0].
        """
        try:
            code = artifact[9][1][0]
        except (IndexError, TypeError):
            return None
        return code if isinstance(code, int) else None

    def _get_artifact_content(self, notebook_id: str, artifact_id: str) -> str | None:
        """Fetch artifact HTML content for quiz/flashcard types.

        Args:
            notebook_id: The notebook ID.
            artifact_id: The artifact ID.

        Returns:
            HTML content string, or None if not found.

        Raises:
            ArtifactDownloadError: If API response structure is unexpected.
        """
        result = self._call_rpc(
            self.RPC_GET_INTERACTIVE_HTML, [artifact_id], f"/notebook/{notebook_id}"
        )

        if not result:
            logger.debug(f"Empty response for artifact {artifact_id}")
            return None

        # Response structure: result[0] contains artifact data
        # HTML content is at result[0][9][0]
        try:
            if not isinstance(result, list) or len(result) == 0:
                logger.warning(f"Unexpected response type for {artifact_id}: {type(result)}")
                return None

            data = result[0]
            if not isinstance(data, list):
                logger.warning(f"Unexpected artifact data type: {type(data)}")
                return None

            if len(data) <= 9:
                logger.warning(f"Artifact data too short (len={len(data)}), expected index 9")
                return None

            html_container = data[9]
            if (
                not html_container
                or not isinstance(html_container, list)
                or len(html_container) == 0
            ):
                logger.debug(f"No HTML content in artifact {artifact_id}")
                return None

            return html_container[0]

        except (IndexError, TypeError) as e:
            logger.error(f"Error parsing artifact content for {artifact_id}: {e}")
            # Log truncated response for debugging
            result_preview = str(result)[:500] if result else "None"
            logger.debug(f"Response preview: {result_preview}...")
            raise ArtifactDownloadError(
                "interactive", details=f"Unexpected API response structure: {e}"
            ) from e

    def get_interactive_app_data(self, notebook_id: str, artifact_id: str) -> dict[str, Any] | None:
        """Return the structured app data of a quiz, flashcard deck or mind map.

        Reuses the download path's HTML fetch and ``data-app-data`` extraction
        so review content matches what ``download_artifact`` saves.
        """
        html_content = self._get_artifact_content(notebook_id, artifact_id)
        if not html_content:
            return None
        return self._extract_app_data(html_content)

    def _extract_app_data(self, html_content: str) -> dict:
        """Extract JSON app data from interactive HTML.

        Quiz and flashcard HTML contains embedded JSON in a data-app-data
        attribute with HTML-encoded content (&quot; for quotes).

        Tries multiple extraction patterns for robustness:
        1. data-app-data attribute (primary)
        2. <script id="application-data"> tag (fallback)
        3. Other common patterns

        Args:
            html_content: The HTML content string.

        Returns:
            Parsed JSON data as dict.

        Raises:
            ArtifactParseError: If data cannot be extracted or parsed.
        """
        # Pattern 1: data-app-data attribute (most common)
        # Handle both single and multiline with greedy matching
        match = re.search(r'data-app-data="([^"]*(?:\\"[^"]*)*)"', html_content, re.DOTALL)
        if match:
            encoded_json = match.group(1)
            decoded_json = html_module.unescape(encoded_json)

            try:
                data = json.loads(decoded_json)
                logger.debug("Extracted app data using data-app-data attribute")
                return data
            except json.JSONDecodeError as e:
                # Log the error but try other patterns
                logger.debug(f"Failed to parse data-app-data JSON: {e}")
                logger.debug(f"JSON preview: {decoded_json[:200]}...")

        # Pattern 2: <script id="application-data"> tag
        match = re.search(
            r'<script[^>]+id=["\']application-data["\'][^>]*>(.*?)</script>',
            html_content,
            re.DOTALL,
        )
        if match:
            try:
                data = json.loads(match.group(1))
                logger.debug("Extracted app data using script tag")
                return data
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse script tag JSON: {e}")

        # Pattern 3: data-state or data-config attributes (additional fallback)
        for attr in ["data-state", "data-config", "data-initial-state"]:
            match = re.search(rf'{attr}="([^"]*(?:\\"[^"]*)*)"', html_content, re.DOTALL)
            if match:
                encoded_json = match.group(1)
                decoded_json = html_module.unescape(encoded_json)
                try:
                    data = json.loads(decoded_json)
                    logger.debug(f"Extracted app data using {attr} attribute")
                    return data
                except json.JSONDecodeError:
                    continue

        # No patterns matched - provide detailed error
        html_preview = html_content[:500] if html_content else "Empty"
        logger.error(f"Failed to extract app data. HTML preview: {html_preview}...")

        raise ArtifactParseError(
            "interactive",
            details=(
                "Could not extract JSON data from HTML. "
                "Tried: data-app-data, script#application-data, data-state, data-config"
            ),
        )

    @staticmethod
    def _format_quiz_markdown(title: str, questions: list[dict]) -> str:
        """Format quiz as markdown.

        Args:
            title: Quiz title.
            questions: List of question dicts with 'question', 'answerOptions', 'hint'.

        Returns:
            Formatted markdown string.
        """
        lines = [f"# {title}", ""]

        for i, q in enumerate(questions, 1):
            lines.append(f"## Question {i}")
            lines.append(q.get("question", ""))
            lines.append("")

            for opt in q.get("answerOptions", []):
                marker = "[x]" if opt.get("isCorrect") else "[ ]"
                lines.append(f"- {marker} {opt.get('text', '')}")

            if q.get("hint"):
                lines.append("")
                lines.append(f"**Hint:** {q['hint']}")

            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_flashcards_markdown(title: str, cards: list[dict]) -> str:
        """Format flashcards as markdown.

        Args:
            title: Flashcard deck title.
            cards: List of card dicts with 'f' (front) and 'b' (back).

        Returns:
            Formatted markdown string.
        """
        lines = [f"# {title}", ""]

        for i, card in enumerate(cards, 1):
            front = card.get("f", "")
            back = card.get("b", "")

            lines.append(f"## Card {i}")
            lines.append("")
            lines.append(f"**Front:** {front}")
            lines.append("")
            lines.append(f"**Back:** {back}")
            lines.append("")
            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    def _format_interactive_content(
        self,
        app_data: dict,
        title: str,
        output_format: str,
        html_content: str,
        is_quiz: bool,
    ) -> str:
        """Format quiz or flashcard content for output.

        Args:
            app_data: Parsed JSON data from HTML.
            title: Artifact title.
            output_format: Output format - json, markdown, or html.
            html_content: Original HTML content.
            is_quiz: True for quiz, False for flashcards.

        Returns:
            Formatted content string.
        """
        if output_format == "html":
            return html_content

        if is_quiz:
            questions = app_data.get("quiz", [])
            if output_format == "markdown":
                return self._format_quiz_markdown(title, questions)
            return json.dumps(
                {"title": title, "questions": questions}, indent=2, ensure_ascii=False
            )

        # Flashcards
        cards = app_data.get("flashcards", [])
        if output_format == "markdown":
            return self._format_flashcards_markdown(title, cards)

        # Normalize JSON format: {"f": "...", "b": "..."} -> {"front": "...", "back": "..."}
        normalized = [{"front": c.get("f", ""), "back": c.get("b", "")} for c in cards]
        return json.dumps({"title": title, "cards": normalized}, indent=2, ensure_ascii=False)

    async def _download_interactive_artifact(
        self,
        notebook_id: str,
        output_path: str,
        artifact_type: str,
        is_quiz: bool,
        artifact_id: str | None = None,
        output_format: str = "json",
    ) -> str:
        """Shared implementation for downloading quiz/flashcard artifacts.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the file.
            artifact_type: Human-readable type for error messages ("quiz" or "flashcards").
            is_quiz: True for quiz, False for flashcards.
            artifact_id: Specific artifact ID, or uses first completed artifact.
            output_format: Output format - json, markdown, or html.

        Returns:
            The output path where the file was saved.

        Raises:
            ValueError: If invalid output_format.
            ArtifactNotReadyError: If no completed artifact found.
            ArtifactParseError: If content parsing fails.
            ArtifactDownloadError: If content fetch fails.
        """
        # Validate format
        valid_formats = ("json", "markdown", "html")
        if output_format not in valid_formats:
            raise ValueError(
                f"Invalid output_format: {output_format!r}. Use one of: {', '.join(valid_formats)}"
            )

        # Get all artifacts and filter for completed interactive artifacts
        artifacts = self._list_raw(notebook_id)

        # Type 4 (STUDIO_TYPE_FLASHCARDS) covers quizzes, flashcards, AND mind
        # maps — distinguished by the format code at [9][1][0] (1=flashcards,
        # 2=quiz, 4=mind map). Status 3 = completed.
        def _matches_subtype(a: Any) -> bool:
            code = self._interactive_format_code(a)
            if is_quiz:
                return code == 2
            # Flashcards: accept legacy entries without a readable code, but
            # never quizzes or mind maps.
            return code not in (2, 4)

        candidates = [
            a
            for a in artifacts
            if isinstance(a, list)
            and len(a) > 4
            and a[2] == self.STUDIO_TYPE_FLASHCARDS
            and a[4] == 3
            and _matches_subtype(a)
        ]

        if not candidates:
            raise ArtifactNotReadyError(artifact_type)

        # Select artifact by ID or use most recent
        if artifact_id:
            target = next((a for a in candidates if a[0] == artifact_id), None)
            if not target:
                raise ArtifactNotReadyError(artifact_type, artifact_id)
        else:
            target = candidates[0]  # Most recent

        # Fetch HTML content
        html_content = self._get_artifact_content(notebook_id, target[0])
        if not html_content:
            raise ArtifactDownloadError(
                artifact_type, details="Failed to fetch HTML content from API"
            )

        # Extract and parse embedded JSON
        try:
            app_data = self._extract_app_data(html_content)
        except ArtifactParseError:
            raise  # Re-raise as-is
        except (ValueError, json.JSONDecodeError) as e:
            raise ArtifactParseError(artifact_type, details=str(e)) from e

        # Get title from artifact metadata
        default_title = f"Untitled {artifact_type.title()}"
        title = target[1] if len(target) > 1 and target[1] else default_title

        # Format content
        content = self._format_interactive_content(
            app_data, title, output_format, html_content, is_quiz
        )

        # Write to file
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")

        logger.info(f"Downloaded {artifact_type} to {output} ({output_format} format)")
        return str(output)

    async def download_quiz(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        output_format: str = "json",
    ) -> str:
        """Download quiz artifact.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the file.
            artifact_id: Specific artifact ID, or uses first completed quiz.
            output_format: Output format - json, markdown, or html (default: json).

        Returns:
            The output path where the file was saved.

        Raises:
            ValueError: If invalid output_format.
            ArtifactNotReadyError: If no completed quiz found.
            ArtifactParseError: If content parsing fails.
        """
        return await self._download_interactive_artifact(
            notebook_id=notebook_id,
            output_path=output_path,
            artifact_type="quiz",
            is_quiz=True,
            artifact_id=artifact_id,
            output_format=output_format,
        )

    async def download_flashcards(
        self,
        notebook_id: str,
        output_path: str,
        artifact_id: str | None = None,
        output_format: str = "json",
    ) -> str:
        """Download flashcard deck artifact.

        Args:
            notebook_id: The notebook ID.
            output_path: Path to save the file.
            artifact_id: Specific artifact ID, or uses first completed flashcard deck.
            output_format: Output format - json, markdown, or html (default: json).

        Returns:
            The output path where the file was saved.

        Raises:
            ValueError: If invalid output_format.
            ArtifactNotReadyError: If no completed flashcards found.
            ArtifactParseError: If content parsing fails.
        """
        return await self._download_interactive_artifact(
            notebook_id=notebook_id,
            output_path=output_path,
            artifact_type="flashcards",
            is_quiz=False,
            artifact_id=artifact_id,
            output_format=output_format,
        )
