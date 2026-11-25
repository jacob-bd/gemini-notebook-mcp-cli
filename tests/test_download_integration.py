"""Integration tests for Download functionalities.

Targeting Notebook: 4085e211-fdb0-4802-b973-b43b9f99b6f7
This notebook is expected to contain all studio artifacts (Audio, Video, etc.).

Run with: NOTEBOOKLM_E2E=1 pytest tests/test_download_integration.py -v
"""

import os
import shutil
from pathlib import Path

import pytest

from notebooklm_tools.core.client import NotebookLMClient
from notebooklm_tools.core.errors import ArtifactNotReadyError

# Target notebook ID provided by user
NOTEBOOK_ID = "4085e211-fdb0-4802-b973-b43b9f99b6f7"

pytestmark = pytest.mark.skipif(
    not os.environ.get("NOTEBOOKLM_E2E"),
    reason="Integration tests disabled. Set NOTEBOOKLM_E2E=1 to run.",
)


@pytest.fixture(scope="module")
def client():
    """Create a client with cached credentials."""
    from notebooklm_tools.core.auth import load_cached_tokens

    tokens = load_cached_tokens()
    if not tokens:
        pytest.skip("No cached credentials. Run 'nlm login' first.")

    return NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id,
    )


@pytest.fixture(scope="module")
def output_dir():
    """Create a temporary output directory."""
    path = Path("tests/output")
    path.mkdir(parents=True, exist_ok=True)
    yield path
    # Cleanup
    shutil.rmtree(path, ignore_errors=True)


class TestClientDownloads:
    """Test client download methods directly."""

    def test_download_report(self, client, output_dir):
        output = output_dir / "report.md"
        path = client.download_report(NOTEBOOK_ID, str(output))
        assert Path(path).exists()
        assert Path(path).stat().st_size > 0
        assert output.read_text().startswith("#")  # Markdown header

    def test_download_audio(self, client, output_dir):
        output = output_dir / "audio.mp4"
        try:
            path = client.download_audio(NOTEBOOK_ID, str(output))
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0
        except ArtifactNotReadyError:
            pytest.skip("Audio artifact not ready")

    def test_download_video(self, client, output_dir):
        output = output_dir / "video.mp4"
        try:
            path = client.download_video(NOTEBOOK_ID, str(output))
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0
        except ArtifactNotReadyError:
            pytest.skip("Video artifact not ready")

    def test_download_infographic(self, client, output_dir):
        output = output_dir / "infographic.png"
        try:
            path = client.download_infographic(NOTEBOOK_ID, str(output))
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0
        except ArtifactNotReadyError:
            pytest.skip("Infographic artifact not ready")

    def test_download_slide_deck(self, client, output_dir):
        output = output_dir / "slides.pdf"
        try:
            path = client.download_slide_deck(NOTEBOOK_ID, str(output))
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0
        except ArtifactNotReadyError:
            pytest.skip("Slide deck artifact not ready")

    def test_download_mind_map(self, client, output_dir):
        output = output_dir / "mindmap.json"
        try:
            path = client.download_mind_map(NOTEBOOK_ID, str(output))
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0
        except ArtifactNotReadyError:
            pytest.skip("Mind map artifact not ready")

    def test_download_data_table(self, client, output_dir):
        output = output_dir / "table.csv"
        try:
            path = client.download_data_table(NOTEBOOK_ID, str(output))
            assert Path(path).exists()
            assert Path(path).stat().st_size > 0
        except ArtifactNotReadyError:
            pytest.skip("Data table artifact not ready")


@pytest.fixture(scope="module")
def auth_check():
    """Check if authentication is available for CLI."""
    from notebooklm_tools.core.auth import load_cached_tokens

    if not load_cached_tokens():
        pytest.skip("No cached credentials for CLI tests")


class TestCLIDownloads:
    """Test CLI download commands."""

    def test_cli_download_report(self, output_dir, auth_check):
        import subprocess

        output = output_dir / "cli_report.md"
        result = subprocess.run(
            ["nlm", "download", "report", NOTEBOOK_ID, "--output", str(output)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            if "not ready" in result.stderr:
                pytest.skip("Report not ready")
            if "No authentication found" in result.stdout:
                pytest.skip("CLI reported no authentication")

            # Fail with details
            raise AssertionError(
                f"CLI failed (code {result.returncode}): {result.stderr}\nStdout: {result.stdout}"
            )

        assert result.returncode == 0
        assert output.exists()


class TestMCPDownloads:
    """Test MCP tool functions."""

    @pytest.mark.skip(reason="Needs update for FastMCP tool objects")
    def test_mcp_download_report(self, output_dir):
        # We need to mock get_client or ensure environment is set up
        # Since we are in the same process, we can patch get_client
        from notebooklm_tools.core.auth import load_cached_tokens
        from notebooklm_tools.mcp.server import download_report

        # Setup tokens specifically for MCP tool which uses get_client() logic
        tokens = load_cached_tokens()
        if not tokens:
            pytest.skip("No cached credentials")

        # Set env vars so get_client picks them up
        os.environ["NOTEBOOKLM_COOKIES"] = tokens.cookie_header
        if tokens.csrf_token:
            os.environ["NOTEBOOKLM_CSRF_TOKEN"] = tokens.csrf_token
        if tokens.session_id:
            os.environ["NOTEBOOKLM_SESSION_ID"] = tokens.session_id

        output = output_dir / "mcp_report.md"

        # Test tool execution
        result = download_report(notebook_id=NOTEBOOK_ID, output_path=str(output))

        # Check result dict
        if result.get("status") == "error":
            if "not ready" in str(result.get("error")):
                pytest.skip("Report not ready")
            pytest.fail(f"MCP Tool failed: {result.get('error')}")

        assert result["status"] == "success"
        assert Path(result["path"]).exists()


def test_cli_and_mcp_reject_login_page_redirects(tmp_path, monkeypatch):
    """Live check: an expired download must not be saved as an artifact."""
    from unittest.mock import patch

    from typer.testing import CliRunner

    from notebooklm_tools.cli.main import app
    from notebooklm_tools.core.download import DownloadMixin
    from notebooklm_tools.mcp.tools import downloads as mcp_downloads

    monkeypatch.setenv("NOTEBOOKLM_DOWNLOAD_DIR", str(tmp_path))

    class ExpiredDownloadClient:
        def download_file(self, notebook_id, output_path, artifact_id=None):
            mixin = DownloadMixin(cookies={"SID": "invalid"}, csrf_token="invalid")
            return mixin._download_url_sync("https://notebook.google.com/", output_path)

    cli_out = tmp_path / "cli.bin"
    with patch(
        "notebooklm_tools.cli.commands.download.get_client",
        return_value=ExpiredDownloadClient(),
    ):
        result = CliRunner().invoke(app, ["download", "file", "nb-1", "--output", str(cli_out)])

    assert result.exit_code == 1
    assert "nlm login" in result.output
    assert not cli_out.exists()

    with patch(
        "notebooklm_tools.mcp.tools.downloads.get_client",
        return_value=ExpiredDownloadClient(),
    ):
        mcp_result = mcp_downloads.download_artifact("nb-1", "file", "mcp.bin")

    assert mcp_result["status"] == "error"
    assert "nlm login" in mcp_result["hint"]
    assert not (tmp_path / "mcp.bin").exists()
