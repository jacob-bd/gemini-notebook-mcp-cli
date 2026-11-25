"""Unit tests for the download_all_artifacts MCP tool."""

from unittest.mock import AsyncMock, MagicMock, patch

from notebooklm_tools.mcp.tools import downloads
from notebooklm_tools.services.errors import ServiceError, ValidationError


def _single_result(**overrides):
    result = {
        "notebook_id": "nb-1",
        "notebook_title": "My Notebook",
        "output_dir": "/tmp/exports/My Notebook",
        "items": [],
        "skipped": [],
        "total_artifacts": 0,
        "downloaded": 0,
        "failed": 0,
    }
    result.update(overrides)
    return result


def _sweep_result(**overrides):
    result = {
        "output_dir": "/tmp/exports",
        "notebooks": [],
        "total_notebooks": 0,
        "downloaded": 0,
        "failed": 0,
        "errored_notebooks": 0,
    }
    result.update(overrides)
    return result


def test_requires_either_notebook_id_or_all_notebooks():
    result = downloads.download_all_artifacts()

    assert result["status"] == "error"
    assert "Provide either notebook_id or all_notebooks" in result["error"]


def test_rejects_both_notebook_id_and_all_notebooks():
    result = downloads.download_all_artifacts(notebook_id="nb-1", all_notebooks=True)

    assert result["status"] == "error"
    assert "not both" in result["error"]


def test_single_notebook_success_routes_to_download_all():
    mock_client = MagicMock()
    service_result = _single_result(downloaded=2, failed=0)

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all",
            return_value=service_result,
        ) as mock_download_all,
    ):
        result = downloads.download_all_artifacts(notebook_id="nb-1", output_dir="exports")

    mock_download_all.assert_called_once_with(
        mock_client,
        "nb-1",
        "exports",
        artifact_types=None,
        output_format="json",
        slide_deck_format="pdf",
        skip_existing=False,
        enforce_root=True,
    )
    assert result["status"] == "success"
    assert result["downloaded"] == 2


def test_single_notebook_partial_status_when_some_downloads_fail():
    mock_client = MagicMock()
    service_result = _single_result(downloaded=1, failed=1)

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all",
            return_value=service_result,
        ),
    ):
        result = downloads.download_all_artifacts(notebook_id="nb-1")

    assert result["status"] == "partial"


def test_single_notebook_error_status_when_nothing_downloaded():
    mock_client = MagicMock()
    service_result = _single_result(downloaded=0, failed=3)

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all",
            return_value=service_result,
        ),
    ):
        result = downloads.download_all_artifacts(notebook_id="nb-1")

    assert result["status"] == "error"


def test_all_notebooks_routes_to_sweep_and_coerces_types():
    mock_client = MagicMock()
    service_result = _sweep_result(total_notebooks=3, downloaded=5)

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all_notebooks",
            return_value=service_result,
        ) as mock_sweep,
    ):
        result = downloads.download_all_artifacts(
            all_notebooks=True,
            output_dir="exports",
            artifact_types="video,report",
            skip_existing=True,
        )

    mock_sweep.assert_called_once_with(
        mock_client,
        "exports",
        artifact_types=["video", "report"],
        output_format="json",
        slide_deck_format="pdf",
        skip_existing=True,
        enforce_root=True,
    )
    assert result["status"] == "success"
    assert result["total_notebooks"] == 3


def test_all_notebooks_partial_status_when_a_notebook_errors():
    mock_client = MagicMock()
    service_result = _sweep_result(downloaded=2, errored_notebooks=1)

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all_notebooks",
            return_value=service_result,
        ),
    ):
        result = downloads.download_all_artifacts(all_notebooks=True)

    assert result["status"] == "partial"


def test_validation_error_is_reported_without_hint():
    mock_client = MagicMock()

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all",
            side_effect=ValidationError("Unknown artifact type 'bogus'."),
        ),
    ):
        result = downloads.download_all_artifacts(notebook_id="nb-1")

    assert result["status"] == "error"
    assert "Unknown artifact type" in result["error"]


def test_service_error_surfaces_user_message_and_hint():
    mock_client = MagicMock()

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_all",
            side_effect=ServiceError(
                "boom", user_message="Notebook not found.", hint="Check the ID."
            ),
        ),
    ):
        result = downloads.download_all_artifacts(notebook_id="nb-1")

    assert result["status"] == "error"
    assert result["error"] == "Notebook not found."
    assert result["hint"] == "Check the ID."


def test_download_artifact_forwards_readiness_options():
    mock_client = MagicMock()
    service_result = {"artifact_type": "audio", "path": "/tmp/audio.m4a"}

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_async",
            new=AsyncMock(return_value=service_result),
        ) as download_async,
    ):
        result = downloads.download_artifact(
            notebook_id="nb-1",
            artifact_type="audio",
            output_path="/tmp/audio.m4a",
            wait=True,
            wait_timeout=9,
            poll_interval=0.5,
        )

    assert result["status"] == "success"
    download_async.assert_awaited_once_with(
        mock_client,
        "nb-1",
        "audio",
        "/tmp/audio.m4a",
        artifact_id=None,
        output_format="json",
        slide_deck_format="pdf",
        enforce_root=True,
        wait=True,
        wait_timeout=9,
        poll_interval=0.5,
    )


def test_download_artifact_auth_error_surfaces_login_hint():
    mock_client = MagicMock()
    error = ServiceError(
        "Failed to download file: auth expired",
        user_message=(
            "Authentication expired while downloading file. Run 'nlm login' to refresh credentials."
        ),
        hint="Run 'nlm login' to refresh credentials.",
        debug_code="auth_required",
    )

    with (
        patch("notebooklm_tools.mcp.tools.downloads.get_client", return_value=mock_client),
        patch(
            "notebooklm_tools.mcp.tools.downloads.downloads_service.download_async",
            new=AsyncMock(side_effect=error),
        ),
    ):
        result = downloads.download_artifact("nb-1", "file", "artifact.bin")

    assert result["status"] == "error"
    assert "Authentication expired while downloading file" in result["error"]
    assert "nlm login" in result["hint"]
