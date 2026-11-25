"""Tests for individual artifact download CLI commands."""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from notebooklm_tools.cli.commands import download
from notebooklm_tools.services.errors import ServiceError


def test_data_table_download_uses_xlsx_extension_for_xlsx_artifact():
    client = MagicMock()
    status = {
        "artifacts": [
            {
                "artifact_id": "xlsx-1",
                "type": "data_table_xlsx",
                "status": "completed",
            }
        ]
    }

    with (
        patch("notebooklm_tools.cli.commands.download.get_alias_manager") as get_alias_manager,
        patch("notebooklm_tools.cli.commands.download.get_client", return_value=client),
        patch(
            "notebooklm_tools.cli.commands.download.downloads_service.get_studio_status",
            return_value=status,
        ) as get_status,
        patch("notebooklm_tools.cli.commands.download._simple_download") as simple_download,
    ):
        get_alias_manager.return_value.resolve.side_effect = lambda value: value

        download.download_data_table("nb-1", output=None, artifact_id=None)

    get_status.assert_called_once_with(client, "nb-1", include_details=False)
    simple_download.assert_called_once_with(
        "nb-1", "data_table", None, None, "table.xlsx", client=client
    )


def test_data_table_download_keeps_csv_extension_for_csv_artifact():
    client = MagicMock()
    status = {
        "artifacts": [
            {
                "artifact_id": "csv-1",
                "type": "data_table",
                "status": "completed",
            }
        ]
    }

    with (
        patch("notebooklm_tools.cli.commands.download.get_alias_manager") as get_alias_manager,
        patch("notebooklm_tools.cli.commands.download.get_client", return_value=client),
        patch(
            "notebooklm_tools.cli.commands.download.downloads_service.get_studio_status",
            return_value=status,
        ),
        patch("notebooklm_tools.cli.commands.download._simple_download") as simple_download,
    ):
        get_alias_manager.return_value.resolve.side_effect = lambda value: value

        download.download_data_table("nb-1", output=None, artifact_id=None)

    simple_download.assert_called_once_with(
        "nb-1", "data_table", None, None, "table.csv", client=client
    )


def test_data_table_download_preserves_explicit_output_without_status_lookup():
    with (
        patch("notebooklm_tools.cli.commands.download.get_alias_manager") as get_alias_manager,
        patch("notebooklm_tools.cli.commands.download.get_client") as get_client,
        patch(
            "notebooklm_tools.cli.commands.download.downloads_service.get_studio_status"
        ) as get_status,
        patch("notebooklm_tools.cli.commands.download._simple_download") as simple_download,
    ):
        get_alias_manager.return_value.resolve.side_effect = lambda value: value

        download.download_data_table("nb-1", output="custom.xlsx", artifact_id="xlsx-1")

    get_client.assert_not_called()
    get_status.assert_not_called()
    simple_download.assert_called_once_with(
        "nb-1", "data_table", "custom.xlsx", "xlsx-1", "table.csv"
    )


def test_download_file_surfaces_auth_error_with_login_hint(tmp_path):
    client = MagicMock()
    error = ServiceError(
        "Failed to download file: auth expired",
        user_message=(
            "Authentication expired while downloading file. Run 'nlm login' to refresh credentials."
        ),
        hint="Run 'nlm login' to refresh credentials.",
        debug_code="auth_required",
    )

    with (
        patch("notebooklm_tools.cli.commands.download.get_alias_manager") as get_alias_manager,
        patch("notebooklm_tools.cli.commands.download.get_client", return_value=client),
        patch(
            "notebooklm_tools.cli.commands.download.downloads_service.download_sync",
            side_effect=error,
        ),
    ):
        get_alias_manager.return_value.resolve.side_effect = lambda value: value
        result = CliRunner().invoke(
            download.app,
            ["file", "nb-1", "--output", str(tmp_path / "artifact.bin")],
        )

    assert result.exit_code == 1
    assert "Authentication expired while downloading file" in result.output
    assert "nlm login" in result.output
    assert not (tmp_path / "artifact.bin").exists()
