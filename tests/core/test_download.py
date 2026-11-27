#!/usr/bin/env python3
"""Tests for DownloadMixin."""

import os
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from notebooklm_tools.core.base import BaseClient
from notebooklm_tools.core.download import DownloadMixin, _create_download_temp_path
from notebooklm_tools.core.errors import (
    ArtifactDownloadError,
    ArtifactParseError,
    ClientAuthenticationError,
)


def test_download_temp_paths_are_unique_and_same_directory(tmp_path):
    output = tmp_path / "artifact.bin"
    first = _create_download_temp_path(output)
    second = _create_download_temp_path(output)
    try:
        assert first != second
        assert first.parent == tmp_path
        assert second.parent == tmp_path
        assert first.name.startswith(".nlm-download-")
        assert second.name.startswith(".nlm-download-")
        assert first.exists()
        assert second.exists()
    finally:
        first.unlink(missing_ok=True)
        second.unlink(missing_ok=True)


def test_failed_download_cleans_only_its_own_temp_file(tmp_path):
    mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
    output = tmp_path / "artifact.bin"
    unrelated = _create_download_temp_path(output)
    unrelated.write_bytes(b"keep")

    request = httpx.Request("GET", "https://example.com/file")
    response = httpx.Response(500, request=request)

    class FailingResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def raise_for_status(self):
            raise httpx.HTTPStatusError("boom", request=request, response=response)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url):
            return FailingResponse()

    try:
        with (
            patch("notebooklm_tools.core.download.httpx.Client", FakeClient),
            pytest.raises(ArtifactDownloadError),
        ):
            mixin._download_url_sync("https://example.com/file", str(output))

        assert unrelated.read_bytes() == b"keep"
        assert list(tmp_path.glob(".nlm-download-*.tmp")) == [unrelated]
        assert not output.exists()
    finally:
        unrelated.unlink(missing_ok=True)


class TestDownloadMixinImport:
    """Test that DownloadMixin can be imported correctly."""

    def test_download_mixin_import(self):
        """Test that DownloadMixin can be imported."""
        assert DownloadMixin is not None

    def test_download_mixin_inherits_base(self):
        """Test that DownloadMixin inherits from BaseClient."""
        assert issubclass(DownloadMixin, BaseClient)

    def test_download_mixin_has_binary_download_methods(self):
        """Test that DownloadMixin has binary download methods."""
        expected_methods = [
            "download_audio",
            "download_video",
            "download_infographic",
            "download_slide_deck",
        ]
        for method in expected_methods:
            assert hasattr(DownloadMixin, method), f"Missing method: {method}"

    def test_download_mixin_has_text_download_methods(self):
        """Test that DownloadMixin has text download methods."""
        expected_methods = [
            "download_report",
            "download_mind_map",
            "download_data_table",
        ]
        for method in expected_methods:
            assert hasattr(DownloadMixin, method), f"Missing method: {method}"

    def test_download_mixin_has_interactive_download_methods(self):
        """Test that DownloadMixin has interactive download methods."""
        expected_methods = [
            "download_quiz",
            "download_flashcards",
        ]
        for method in expected_methods:
            assert hasattr(DownloadMixin, method), f"Missing method: {method}"

    def test_download_mixin_has_helper_methods(self):
        """Test that DownloadMixin has helper methods."""
        expected_methods = [
            "_download_url",
            "_list_raw",
            "_extract_cell_text",
            "_parse_data_table",
            "_get_artifact_content",
            "_extract_app_data",
        ]
        for method in expected_methods:
            assert hasattr(DownloadMixin, method), f"Missing method: {method}"


class TestDownloadMixinMethods:
    """Test DownloadMixin method behavior."""

    def _video_artifact(self, url: str) -> list:
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        artifact = ["video-1", None, mixin.STUDIO_TYPE_VIDEO, None, 3]
        artifact.extend([None] * 3)
        artifact.append([[[url, 4, "video/mp4"]]])
        return artifact

    def _audio_artifact(self, url: str) -> list:
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        return [
            "art-1",
            "Audio",
            mixin.STUDIO_TYPE_AUDIO,
            [],
            2,
            None,
            [
                None,
                ["", 2, None, [["src-1"]], "en", True, 1],
                "https://example.com/thumb",
                "https://example.com/thumb-dv",
                None,
                [[url, 4, "audio/mp4"]],
                [],
            ],
        ]

    @staticmethod
    def _xlsx_artifact() -> list:
        artifact = [
            "xlsx-1",
            "sawn-lumber-design.xlsx",
            10,
            None,
            3,
        ]
        artifact.extend([None] * 20)
        artifact[24] = [
            "sawn-lumber-design.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "https://drive.google.com/viewer/upload?ds=viewer-token",
            "https://contribution.usercontent.google/download?c=download-token",
        ]
        return artifact

    def test_download_data_table_streams_xlsx_artifact(self, tmp_path):
        """Type-10 data tables are downloaded as binary XLSX, not parsed as CSV."""
        mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
        mixin._list_raw = Mock(return_value=[self._xlsx_artifact()])
        captured: dict[str, str] = {}

        class FakeResponse:
            headers = {
                "content-length": "7",
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def raise_for_status(self):
                return None

            def iter_bytes(self, chunk_size=65536):
                yield b"PK\x03\x04"
                yield b"xlsx"

        class FakeClient:
            def __init__(self, **kwargs):
                captured["url"] = ""

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def stream(self, method, url):
                captured["method"] = method
                captured["url"] = url
                return FakeResponse()

        output = tmp_path / "table.xlsx"
        output.write_bytes(b"old")
        with patch("notebooklm_tools.core.download.httpx.Client", FakeClient):
            result = mixin.download_data_table("nb-1", str(output), "xlsx-1")

        assert result == str(output)
        assert output.read_bytes() == b"PK\x03\x04xlsx"
        assert not list(tmp_path.glob(".nlm-download-*.tmp"))
        assert captured == {
            "method": "GET",
            "url": "https://contribution.usercontent.google/download?c=download-token",
        }

    @staticmethod
    def _generic_file_artifact(metadata: list[str]) -> list:
        artifact = ["file-1", "analysis.md", 10, None, 3]
        artifact.extend([None] * 20)
        artifact[24] = metadata
        return artifact

    def test_download_file_streams_direct_export_url(self, tmp_path):
        mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
        direct_url = "https://contribution.usercontent.google/download?c=file-token"
        mixin._list_raw = Mock(
            return_value=[
                self._generic_file_artifact(
                    [
                        "analysis.md",
                        "text/markdown",
                        "https://drive.google.com/viewer/upload?ds=viewer-token",
                        direct_url,
                    ]
                )
            ]
        )
        requested_urls: list[str] = []

        class FakeResponse:
            headers = {"content-length": "8", "content-type": "text/markdown"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def raise_for_status(self):
                return None

            def iter_bytes(self, chunk_size=65536):
                yield b"# Answer"

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def stream(self, method, url):
                requested_urls.append(url)
                return FakeResponse()

        output = tmp_path / "analysis.md"
        with patch("notebooklm_tools.core.download.httpx.Client", FakeClient):
            result = mixin.download_file("nb-1", str(output), "file-1")

        assert result == str(output)
        assert output.read_text(encoding="utf-8") == "# Answer"
        assert requested_urls == [direct_url]

    @pytest.mark.parametrize(
        ("output_name", "resolved_name"),
        [("analysis.md", "analysis.pdf"), ("nb_file.bin", "nb_file.pdf")],
    )
    def test_download_file_resolves_trusted_viewer_envelope(
        self, tmp_path, output_name, resolved_name
    ):
        mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
        viewer_url = "https://drive.google.com/viewer/upload?ds=viewer-token"
        pdf_url = "https://doc-1-apps-viewer.googleusercontent.com/file.pdf"
        mixin._list_raw = Mock(
            return_value=[self._generic_file_artifact(["analysis.md", "text/markdown", viewer_url])]
        )
        requested_urls: list[str] = []

        class ViewerResponse:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                return None

            def json(self):
                return {"pdf": pdf_url, "meta": "redacted"}

        class DownloadResponse:
            headers = {"content-length": "8", "content-type": "application/pdf"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def raise_for_status(self):
                return None

            def iter_bytes(self, chunk_size=65536):
                yield b"%PDF-1.7"

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def get(self, url):
                requested_urls.append(url)
                return ViewerResponse()

            def stream(self, method, url):
                requested_urls.append(url)
                return DownloadResponse()

        output = tmp_path / output_name
        resolved_output = tmp_path / resolved_name
        with patch("notebooklm_tools.core.download.httpx.Client", FakeClient):
            result = mixin.download_file("nb-1", str(output), "file-1")

        assert result == str(resolved_output)
        assert resolved_output.read_bytes() == b"%PDF-1.7"
        assert not output.exists()
        assert requested_urls == [viewer_url, pdf_url]

    def test_download_file_rejects_untrusted_viewer_target(self, tmp_path):
        mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
        viewer_url = "https://drive.google.com/viewer/upload?ds=viewer-token"
        mixin._list_raw = Mock(
            return_value=[self._generic_file_artifact(["analysis.md", "text/markdown", viewer_url])]
        )

        class ViewerResponse:
            status_code = 200
            headers = {}

            def raise_for_status(self):
                return None

            def json(self):
                return {"pdf": "https://evil.example/file.pdf"}

        class FakeClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return None

            def get(self, url):
                return ViewerResponse()

            def stream(self, method, url):
                raise AssertionError("untrusted target must not be downloaded")

        output = tmp_path / "analysis.pdf"
        with (
            patch("notebooklm_tools.core.download.httpx.Client", FakeClient),
            pytest.raises(ArtifactParseError, match="trusted Google host"),
        ):
            mixin.download_file("nb-1", str(output), "file-1")

        assert not output.exists()

    def _download_error(self, status_code: int, final_url: str) -> ArtifactDownloadError:
        request = httpx.Request("GET", final_url)
        response = httpx.Response(status_code, request=request)
        cause = httpx.HTTPStatusError("download failed", request=request, response=response)
        error = ArtifactDownloadError("file", details="HTTP error")
        error.__cause__ = cause
        return error

    def test_extract_cell_text_handles_none(self):
        """Test that _extract_cell_text handles None input."""
        result = DownloadMixin._extract_cell_text(None)
        assert result == ""

    def test_extract_cell_text_handles_string(self):
        """Test that _extract_cell_text handles string input."""
        result = DownloadMixin._extract_cell_text("  test value  ")
        assert result == "test value"

    def test_extract_cell_text_handles_integer(self):
        """Test that _extract_cell_text handles integer input (position marker)."""
        result = DownloadMixin._extract_cell_text(42)
        assert result == ""

    def test_extract_cell_text_handles_nested_list(self):
        """Test that _extract_cell_text handles nested list input."""
        result = DownloadMixin._extract_cell_text([1, "hello", [2, "world"]])
        assert "hello" in result
        assert "world" in result

    def test_format_quiz_markdown(self):
        """Test quiz markdown formatting."""
        questions = [
            {
                "question": "What is 2+2?",
                "answerOptions": [
                    {"text": "3", "isCorrect": False},
                    {"text": "4", "isCorrect": True},
                ],
                "hint": "Think simple",
            }
        ]
        result = DownloadMixin._format_quiz_markdown("Test Quiz", questions)
        assert "# Test Quiz" in result
        assert "## Question 1" in result
        assert "What is 2+2?" in result
        assert "[x] 4" in result
        assert "[ ] 3" in result
        assert "**Hint:** Think simple" in result

    def test_format_flashcards_markdown(self):
        """Test flashcard markdown formatting."""
        cards = [{"f": "Front text", "b": "Back text"}]
        result = DownloadMixin._format_flashcards_markdown("Test Deck", cards)
        assert "# Test Deck" in result
        assert "## Card 1" in result
        assert "**Front:** Front text" in result
        assert "**Back:** Back text" in result

    def test_is_audio_artifact_ready_accepts_verified_status_2_payload(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        artifact = [
            "art-1",
            "Audio",
            mixin.STUDIO_TYPE_AUDIO,
            [],
            2,
            None,
            [
                None,
                ["", 2, None, [["src-1"]], "en", True, 1],
                "https://example.com/thumb",
                "https://example.com/thumb-dv",
                None,
                [["https://example.com/audio.m4a", 1, "audio/mp4"]],
                [],
            ],
        ]

        assert mixin._is_audio_artifact_ready(artifact) is True

    @pytest.mark.asyncio
    async def test_download_audio_accepts_verified_status_2_payload(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        artifact = [
            "art-1",
            "Audio",
            mixin.STUDIO_TYPE_AUDIO,
            [],
            2,
            None,
            [
                None,
                ["", 2, None, [["src-1"]], "en", True, 1],
                "https://example.com/thumb",
                "https://example.com/thumb-dv",
                None,
                [["https://example.com/audio.m4a", 1, "audio/mp4"]],
                [],
            ],
        ]

        mixin._list_raw = lambda notebook_id: [artifact]
        mixin._download_url = AsyncMock(return_value="/tmp/audio.m4a")

        result = await mixin.download_audio("nb-1", "/tmp/audio.m4a")

        assert result == "/tmp/audio.m4a"
        mixin._download_url.assert_awaited_once_with(
            "https://example.com/audio.m4a",
            "/tmp/audio.m4a",
            None,
        )

    @pytest.mark.asyncio
    async def test_download_audio_retries_transient_google_media_404(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        first_url = "https://lh3.googleusercontent.com/notebooklm/audio=m140-dv"
        second_url = "https://lh3.googleusercontent.com/notebooklm/audio2=m140-dv"
        retryable_error = self._download_error(
            404,
            "https://lh3.googleusercontent.com/rd-notebooklm/audio=s512-m140-dv",
        )

        mixin._list_raw = Mock(
            side_effect=[
                [self._audio_artifact(first_url)],
                [self._audio_artifact(second_url)],
            ]
        )
        mixin._download_url = AsyncMock(side_effect=[retryable_error, "/tmp/audio.m4a"])
        mixin._AUDIO_DOWNLOAD_RETRY_DELAYS = (0,)

        result = await mixin.download_audio("nb-1", "/tmp/audio.m4a", artifact_id="art-1")

        assert result == "/tmp/audio.m4a"
        assert mixin._list_raw.call_count == 2
        mixin._download_url.assert_any_await(first_url, "/tmp/audio.m4a", None)
        mixin._download_url.assert_any_await(second_url, "/tmp/audio.m4a", None)

    @pytest.mark.asyncio
    async def test_download_audio_retries_transient_drum_media_404(self):
        """The current drum.usercontent.google.com redirect is retryable."""
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        first_url = "https://drum.usercontent.google.com/notebooklm/audio=m140-dv"
        second_url = "https://drum.usercontent.google.com/notebooklm/audio2=m140-dv"
        retryable_error = self._download_error(
            404,
            "https://drum.usercontent.google.com/rd-notebooklm/audio=s512-m140-dv",
        )

        mixin._list_raw = Mock(
            side_effect=[
                [self._audio_artifact(first_url)],
                [self._audio_artifact(second_url)],
            ]
        )
        mixin._download_url = AsyncMock(side_effect=[retryable_error, "/tmp/audio.m4a"])
        mixin._AUDIO_DOWNLOAD_RETRY_DELAYS = (0,)

        result = await mixin.download_audio("nb-1", "/tmp/audio.m4a", artifact_id="art-1")

        assert result == "/tmp/audio.m4a"
        assert mixin._list_raw.call_count == 2
        mixin._download_url.assert_any_await(first_url, "/tmp/audio.m4a", None)
        mixin._download_url.assert_any_await(second_url, "/tmp/audio.m4a", None)

    @pytest.mark.asyncio
    async def test_download_audio_does_not_retry_unrelated_404(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        url = "https://lh3.googleusercontent.com/notebooklm/audio=m140-dv"
        non_retryable_error = self._download_error(
            404,
            "https://example.com/not-found",
        )

        mixin._list_raw = Mock(return_value=[self._audio_artifact(url)])
        mixin._download_url = AsyncMock(side_effect=non_retryable_error)
        mixin._AUDIO_DOWNLOAD_RETRY_DELAYS = (0,)

        with pytest.raises(ArtifactDownloadError) as exc_info:
            await mixin.download_audio("nb-1", "/tmp/audio.m4a", artifact_id="art-1")

        assert exc_info.value is non_retryable_error
        assert mixin._list_raw.call_count == 1
        mixin._download_url.assert_awaited_once_with(url, "/tmp/audio.m4a", None)

    @pytest.mark.asyncio
    async def test_download_audio_reports_propagation_after_retry_exhaustion(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        url = "https://lh3.googleusercontent.com/notebooklm/audio=m140-dv"
        retryable_error = self._download_error(
            404,
            "https://lh3.googleusercontent.com/rd-notebooklm/audio=s512-m140-dv",
        )

        mixin._list_raw = Mock(return_value=[self._audio_artifact(url)])
        mixin._download_url = AsyncMock(side_effect=retryable_error)
        mixin._AUDIO_DOWNLOAD_RETRY_DELAYS = (0,)

        with pytest.raises(ArtifactDownloadError) as exc_info:
            await mixin.download_audio("nb-1", "/tmp/audio.m4a", artifact_id="art-1")

        assert "still propagating" in exc_info.value.details
        assert mixin._list_raw.call_count == 2
        assert mixin._download_url.await_count == 2

    @pytest.mark.asyncio
    async def test_download_video_retries_transient_google_media_404(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        first_url = "https://lh3.googleusercontent.com/notebooklm/video-1"
        second_url = "https://lh3.googleusercontent.com/notebooklm/video-2"
        retryable_error = self._download_error(404, first_url)
        mixin._list_raw = Mock(
            side_effect=[
                [self._video_artifact(first_url)],
                [self._video_artifact(second_url)],
            ]
        )
        mixin._download_url = AsyncMock(side_effect=[retryable_error, "/tmp/video.mp4"])
        mixin._VIDEO_DOWNLOAD_RETRY_DELAYS = (0,)

        result = await mixin.download_video("nb-1", "/tmp/video.mp4", artifact_id="video-1")

        assert result == "/tmp/video.mp4"
        assert mixin._list_raw.call_count == 2
        mixin._download_url.assert_any_await(first_url, "/tmp/video.mp4", None)
        mixin._download_url.assert_any_await(second_url, "/tmp/video.mp4", None)

    @pytest.mark.asyncio
    async def test_download_video_ignores_malformed_secondary_media_entries(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        url = "https://lh3.googleusercontent.com/notebooklm/video-1"
        artifact = self._video_artifact(url)
        artifact[8][0].append(42)
        mixin._list_raw = Mock(return_value=[artifact])
        mixin._download_url = AsyncMock(return_value="/tmp/video.mp4")

        result = await mixin.download_video("nb-1", "/tmp/video.mp4")

        assert result == "/tmp/video.mp4"
        mixin._download_url.assert_awaited_once_with(url, "/tmp/video.mp4", None)

    @pytest.mark.asyncio
    async def test_download_video_does_not_retry_unrelated_404(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        url = "https://lh3.googleusercontent.com/notebooklm/video-1"
        unrelated_error = self._download_error(404, "https://example.com/not-found")
        mixin._list_raw = Mock(return_value=[self._video_artifact(url)])
        mixin._download_url = AsyncMock(side_effect=unrelated_error)
        mixin._VIDEO_DOWNLOAD_RETRY_DELAYS = (0,)

        with pytest.raises(ArtifactDownloadError) as exc_info:
            await mixin.download_video("nb-1", "/tmp/video.mp4", artifact_id="video-1")

        assert exc_info.value is unrelated_error
        mixin._download_url.assert_awaited_once_with(url, "/tmp/video.mp4", None)

    @pytest.mark.asyncio
    async def test_download_video_reports_propagation_after_retry_exhaustion(self):
        mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        url = "https://lh3.googleusercontent.com/notebooklm/video-1"
        retryable_error = self._download_error(404, url)
        mixin._list_raw = Mock(return_value=[self._video_artifact(url)])
        mixin._download_url = AsyncMock(side_effect=retryable_error)
        mixin._VIDEO_DOWNLOAD_RETRY_DELAYS = (0,)

        with pytest.raises(ArtifactDownloadError) as exc_info:
            await mixin.download_video("nb-1", "/tmp/video.mp4", artifact_id="video-1")

        assert "still propagating" in exc_info.value.details
        assert mixin._download_url.await_count == 2


class TestDownloadUrlCookies:
    """Cookie handling for cross-domain artifact downloads."""

    @pytest.mark.asyncio
    async def test_download_url_strips_osid_cookies(self, tmp_path):
        """OSID cookies must be removed before issuing the download request.

        OSID is scoped to notebooklm.google.com. If it leaks onto a download
        host such as lh3.googleusercontent.com, Google treats the request as
        an invalid session and redirects to ServiceLogin.
        """
        mixin = DownloadMixin(
            cookies=[
                {"name": "SID", "value": "sid-value", "domain": ".google.com", "path": "/"},
                {"name": "OSID", "value": "osid-value", "domain": ".google.com", "path": "/"},
                {
                    "name": "__Secure-OSID",
                    "value": "secure-osid-value",
                    "domain": ".google.com",
                    "path": "/",
                },
            ],
            csrf_token="token",
        )

        captured = {}

        class MockStreamResponse:
            headers = {
                "content-length": "4",
                "content-type": "application/octet-stream",
            }

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            def raise_for_status(self):
                return None

            async def aiter_bytes(self, chunk_size=8192):
                yield b"data"

        class MockAsyncClient:
            def __init__(self, *, cookies, headers, follow_redirects, timeout):
                captured["cookies"] = cookies
                captured["headers"] = headers

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            def stream(self, method, url):
                return MockStreamResponse()

        output = tmp_path / "out.bin"
        output.write_bytes(b"old")

        with patch("notebooklm_tools.core.download.httpx.AsyncClient", MockAsyncClient):
            result = await mixin._download_url(
                "https://lh3.googleusercontent.com/file", str(output)
            )

        assert result == str(output)
        assert output.read_bytes() == b"data"
        assert not list(tmp_path.glob(".nlm-download-*.tmp"))

        cookies = captured["cookies"]
        assert cookies.get("SID", domain=".google.com") == "sid-value"
        assert cookies.get("SID", domain=".googleusercontent.com") == "sid-value"
        for domain in (".google.com", ".googleusercontent.com"):
            assert cookies.get("OSID", domain=domain) is None
            assert cookies.get("__Secure-OSID", domain=domain) is None

        headers = captured["headers"]
        assert headers.get("Sec-Fetch-Site") == "cross-site"
        assert headers.get("Referer") == f"{mixin._get_base_url()}/"


class TestDownloadMindMapNoteFiltering:
    """The notes store mixes notes and mind maps; download_mind_map must only
    consider entries whose content is real mind map JSON."""

    @staticmethod
    def _mixin_with_entries(entries):
        from unittest.mock import patch

        from notebooklm_tools.core.download import DownloadMixin

        with patch.object(DownloadMixin, "_refresh_auth_tokens"):
            mixin = DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")
        patcher = patch.object(mixin, "_call_rpc", return_value=[entries])
        patcher.start()
        return mixin, patcher

    _NOTE = [
        "note-1",
        ["note-1", "Prose note content, not JSON.", [None, None, None], None, "A Note"],
        1,
    ]
    _MIND_MAP = [
        "mm-1",
        ["mm-1", '{"name": "Root", "children": []}', [None, None, None], None, "Real Map"],
        1,
    ]

    def test_unqualified_download_skips_notes(self, tmp_path):
        mixin, patcher = self._mixin_with_entries([self._NOTE, self._MIND_MAP])
        try:
            out = mixin.download_mind_map("nb-1", str(tmp_path / "mm.json"))
        finally:
            patcher.stop()
        import json as _json

        data = _json.loads((tmp_path / "mm.json").read_text(encoding="utf-8"))
        assert data == {"name": "Root", "children": []}
        assert out == str(tmp_path / "mm.json")

    def test_note_id_reports_not_found(self, tmp_path):
        import pytest as _pytest

        from notebooklm_tools.core.errors import ArtifactNotFoundError

        mixin, patcher = self._mixin_with_entries([self._NOTE, self._MIND_MAP])
        try:
            with _pytest.raises(ArtifactNotFoundError):
                mixin.download_mind_map("nb-1", str(tmp_path / "mm.json"), "note-1")
        finally:
            patcher.stop()

    def test_only_notes_reports_not_ready(self, tmp_path):
        import pytest as _pytest

        from notebooklm_tools.core.errors import ArtifactNotReadyError

        mixin, patcher = self._mixin_with_entries([self._NOTE])
        try:
            with _pytest.raises(ArtifactNotReadyError):
                mixin.download_mind_map("nb-1", str(tmp_path / "mm.json"))
        finally:
            patcher.stop()


class TestStudioMindMapDownload:
    """Mind maps stored as type-4 studio artifacts (format code 4)."""

    _MM_HTML = (
        '<div data-app-data="{&quot;name&quot;: &quot;Root&quot;, &quot;children&quot;: []}"></div>'
    )

    @staticmethod
    def _raw_type4(artifact_id, title, format_code):
        return [
            artifact_id,
            title,
            4,
            None,
            3,
            None,
            None,
            None,
            None,
            ["", [format_code, None, None, "en", None, None, None, None, True]],
        ]

    @staticmethod
    def _mixin():
        from unittest.mock import patch

        from notebooklm_tools.core.download import DownloadMixin

        with patch.object(DownloadMixin, "_refresh_auth_tokens"):
            return DownloadMixin(cookies={"test": "cookie"}, csrf_token="test")

    def test_download_mind_map_falls_back_to_studio_artifact(self, tmp_path):
        import json as _json
        from unittest.mock import patch

        mixin = self._mixin()
        raw = self._raw_type4("mm-9", "Studio Map", 4)
        with (
            patch.object(mixin, "_call_rpc", return_value=[[]]),  # notes store empty
            patch.object(mixin, "_list_raw", return_value=[raw]),
            patch.object(mixin, "_get_artifact_content", return_value=self._MM_HTML),
        ):
            out = mixin.download_mind_map("nb-1", str(tmp_path / "mm.json"), "mm-9")

        assert out == str(tmp_path / "mm.json")
        data = _json.loads((tmp_path / "mm.json").read_text(encoding="utf-8"))
        assert data == {"name": "Root", "children": []}

    def test_unqualified_download_uses_studio_when_notes_store_empty(self, tmp_path):
        import json as _json
        from unittest.mock import patch

        mixin = self._mixin()
        raw = self._raw_type4("mm-9", "Studio Map", 4)
        with (
            patch.object(mixin, "_call_rpc", return_value=[[]]),
            patch.object(mixin, "_list_raw", return_value=[raw]),
            patch.object(mixin, "_get_artifact_content", return_value=self._MM_HTML),
        ):
            out = mixin.download_mind_map("nb-1", str(tmp_path / "mm.json"))

        data = _json.loads((tmp_path / "mm.json").read_text(encoding="utf-8"))
        assert data["name"] == "Root"
        assert out == str(tmp_path / "mm.json")

    @pytest.mark.asyncio
    async def test_flashcards_download_excludes_mind_maps(self, tmp_path):
        from unittest.mock import patch

        from notebooklm_tools.core.errors import ArtifactNotReadyError

        mixin = self._mixin()
        raw = self._raw_type4("mm-9", "Studio Map", 4)
        with (
            patch.object(mixin, "_list_raw", return_value=[raw]),
            pytest.raises(ArtifactNotReadyError),
        ):
            await mixin.download_flashcards("nb-1", str(tmp_path / "cards.json"))

    @pytest.mark.asyncio
    async def test_quiz_download_still_finds_quiz(self, tmp_path):
        from unittest.mock import patch

        quiz_html = '<div data-app-data="{&quot;quiz&quot;: [{&quot;question&quot;: &quot;Q1&quot;}]}"></div>'
        mixin = self._mixin()
        raws = [
            self._raw_type4("mm-9", "Studio Map", 4),
            self._raw_type4("q-1", "The Quiz", 2),
        ]
        with (
            patch.object(mixin, "_list_raw", return_value=raws),
            patch.object(mixin, "_get_artifact_content", return_value=quiz_html) as mock_content,
        ):
            out = await mixin.download_quiz("nb-1", str(tmp_path / "quiz.json"))

        assert out == str(tmp_path / "quiz.json")
        assert mock_content.call_args[0][1] == "q-1"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_download_temp_file_honors_umask_not_owner_only(tmp_path):
    umask = os.umask(0)
    os.umask(umask)
    temp = _create_download_temp_path(tmp_path / "artifact.bin")
    try:
        assert temp.stat().st_mode & 0o777 == 0o666 & ~umask
    finally:
        temp.unlink(missing_ok=True)


def test_interrupted_download_removes_its_temp_file(tmp_path):
    mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
    output = tmp_path / "artifact.bin"

    class InterruptedClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url):
            raise KeyboardInterrupt

    with (
        patch("notebooklm_tools.core.download.httpx.Client", InterruptedClient),
        pytest.raises(KeyboardInterrupt),
    ):
        mixin._download_url_sync("https://example.com/file", str(output))

    assert not list(tmp_path.glob(".nlm-download-*.tmp"))
    assert not output.exists()


@pytest.mark.asyncio
async def test_download_url_propagates_authentication_error_on_login_redirect(tmp_path):
    """HTML login redirects must raise ClientAuthenticationError, not ArtifactDownloadError."""
    mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
    output = tmp_path / "audio.m4a"
    output.write_bytes(b"existing-audio")

    class LoginRedirectResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def raise_for_status(self):
            return None

        async def aiter_bytes(self, chunk_size=8192):
            yield b"<!doctype html><html><title>Sign in - Google Accounts</title></html>"

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url):
            return LoginRedirectResponse()

    with (
        patch("notebooklm_tools.core.download.httpx.AsyncClient", FakeAsyncClient),
        pytest.raises(ClientAuthenticationError, match="Redirected to login page"),
    ):
        await mixin._download_url("https://lh3.googleusercontent.com/audio", str(output))

    assert output.read_bytes() == b"existing-audio"
    assert not list(tmp_path.glob(".nlm-download-*.tmp"))


def test_download_url_sync_rejects_login_redirect_without_overwriting(tmp_path):
    """Sync downloads must detect HTML login redirects instead of saving HTML as the artifact."""
    mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
    output = tmp_path / "table.xlsx"
    output.write_bytes(b"existing-xlsx")

    class LoginRedirectResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size=65536):
            yield b"<!doctype html><html><title>Sign in - Google Accounts</title></html>"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url):
            return LoginRedirectResponse()

    with (
        patch("notebooklm_tools.core.download.httpx.Client", FakeClient),
        pytest.raises(ClientAuthenticationError, match="Redirected to login page"),
    ):
        mixin._download_url_sync(
            "https://contribution.usercontent.google/download?c=token", str(output)
        )

    assert output.read_bytes() == b"existing-xlsx"
    assert not list(tmp_path.glob(".nlm-download-*.tmp"))


def test_download_url_sync_allows_non_login_html_content(tmp_path):
    """Non-login text/html payloads still stream completely to disk."""
    mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
    output = tmp_path / "snippet.html"

    class HtmlFragmentResponse:
        headers = {"content-type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size=65536):
            yield b"<div>Hello "
            yield b"world</div>"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def stream(self, method, url):
            return HtmlFragmentResponse()

    with patch("notebooklm_tools.core.download.httpx.Client", FakeClient):
        result = mixin._download_url_sync("https://example.com/snippet", str(output))

    assert result == str(output)
    assert output.read_bytes() == b"<div>Hello world</div>"
    assert not list(tmp_path.glob(".nlm-download-*.tmp"))


class TestFileViewerAuthAndRedirectGuards:
    viewer_url = "https://drive.google.com/viewer/upload"
    sign_in_url = "https://accounts.google.com/ServiceLogin"
    pdf_url = "https://doc-1.googleusercontent.com/file.pdf"

    @pytest.fixture
    def viewer(self, monkeypatch):
        client_class = httpx.Client
        mixin = DownloadMixin(cookies={"SID": "cookie"}, csrf_token="test")
        artifact = [None] * 25
        artifact[0] = "file-1"
        artifact[2] = DownloadMixin.STUDIO_TYPE_DATA_TABLE_XLSX
        artifact[4] = 3
        artifact[24] = ["analysis.md", "text/markdown", self.viewer_url]
        mixin._list_raw = Mock(return_value=[artifact])

        def install_transport(handler):
            transport = httpx.MockTransport(handler)
            monkeypatch.setattr(
                httpx, "Client", lambda **kwargs: client_class(transport=transport, **kwargs)
            )

        return mixin, install_transport

    def test_sign_in_redirect_is_reported_without_loading_sign_in_page(self, viewer, tmp_path):
        mixin, install_transport = viewer
        requested = []

        def respond(request):
            requested.append(str(request.url))
            if request.url == self.viewer_url:
                return httpx.Response(302, headers={"location": self.sign_in_url})
            return httpx.Response(200, json={})

        install_transport(respond)
        output = tmp_path / "analysis.pdf"
        with pytest.raises(ClientAuthenticationError, match="Redirected to login page"):
            mixin.download_file("nb-1", str(output), "file-1")

        assert requested == [self.viewer_url]
        assert not output.exists()

    def test_trusted_relative_redirect_resolves_envelope_and_downloads(self, viewer, tmp_path):
        mixin, install_transport = viewer
        responses = {
            self.viewer_url: httpx.Response(302, headers={"location": "/viewer/result"}),
            "https://drive.google.com/viewer/result": httpx.Response(
                200, json={"pdf": self.pdf_url}
            ),
            self.pdf_url: httpx.Response(200, content=b"%PDF-1.7"),
        }
        install_transport(lambda request: responses[str(request.url)])
        output = tmp_path / "analysis.bin"

        assert mixin.download_file("nb-1", str(output), "file-1") == str(output.with_suffix(".pdf"))
        assert output.with_suffix(".pdf").read_bytes() == b"%PDF-1.7"

    @pytest.mark.parametrize("status", [200, 403])
    def test_google_login_html_is_reported_as_authentication_error(self, viewer, tmp_path, status):
        mixin, install_transport = viewer
        install_transport(
            lambda request: httpx.Response(
                status,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"<!doctype html><html><title>Sign in to Google</title></html>",
            )
        )

        with pytest.raises(ClientAuthenticationError, match="Redirected to login page"):
            mixin.download_file("nb-1", str(tmp_path / "analysis.pdf"), "file-1")

    @pytest.mark.parametrize("status", [200, 403])
    def test_generic_viewer_html_is_reported_as_parse_error(self, viewer, tmp_path, status):
        mixin, install_transport = viewer
        install_transport(
            lambda request: httpx.Response(
                status,
                headers={"content-type": "text/html"},
                content=b"<!doctype html><html><title>Viewer unavailable</title></html>",
            )
        )

        with pytest.raises(ArtifactParseError):
            mixin.download_file("nb-1", str(tmp_path / "analysis.pdf"), "file-1")

    def test_http_401_is_reported_as_authentication_error(self, viewer, tmp_path):
        mixin, install_transport = viewer
        install_transport(lambda request: httpx.Response(401))

        with pytest.raises(ClientAuthenticationError, match="HTTP 401"):
            mixin.download_file("nb-1", str(tmp_path / "analysis.pdf"), "file-1")
