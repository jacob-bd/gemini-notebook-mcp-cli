"""End-to-end tests for NotebookLM Tools.

These tests run against the real NotebookLM API using cached credentials.
They require valid authentication (run `nlm login` first).

Run with: pytest tests/test_e2e.py -v
Skip with: pytest tests/ -v --ignore=tests/test_e2e.py
"""

import contextlib
import os
import time
from pathlib import Path

import pytest

# Skip all E2E tests if NOTEBOOKLM_E2E env var is not set
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("NOTEBOOKLM_E2E") != "1",
        reason="E2E tests disabled. Set NOTEBOOKLM_E2E=1 to run.",
    ),
]


@pytest.fixture(scope="module")
def client():
    """Create a client with cached credentials."""
    from notebooklm_tools.core.auth import load_cached_tokens
    from notebooklm_tools.core.client import NotebookLMClient

    tokens = load_cached_tokens()
    if not tokens:
        pytest.skip("No cached credentials. Run 'nlm login' first.")

    return NotebookLMClient(
        cookies=tokens.cookies,
        csrf_token=tokens.csrf_token,
        session_id=tokens.session_id,
    )


@pytest.fixture(scope="module")
def test_notebook(client):
    """Create a test notebook for e2e tests, cleanup after."""
    notebook = client.create_notebook(title=f"E2E Test {int(time.time())}")
    assert notebook is not None, "Failed to create test notebook"

    yield notebook

    # Cleanup (best effort)
    with contextlib.suppress(Exception):
        client.delete_notebook(notebook.id)


class TestNotebookOperations:
    """Test notebook CRUD operations."""

    def test_list_notebooks(self, client):
        """Test listing notebooks."""
        notebooks = client.list_notebooks()
        assert isinstance(notebooks, list)
        # May be empty for new accounts, but should return list
        print(f"Found {len(notebooks)} notebooks")

    def test_create_and_delete_notebook(self, client):
        """Test creating and deleting a notebook."""
        # Create
        notebook = client.create_notebook(title="E2E Delete Test")
        assert notebook is not None
        assert notebook.id is not None
        assert "E2E Delete Test" in notebook.title

        # Delete
        result = client.delete_notebook(notebook.id)
        assert result is True

    def test_rename_notebook(self, client, test_notebook):
        """Test renaming a notebook."""
        new_title = f"Renamed E2E Test {int(time.time())}"
        result = client.rename_notebook(test_notebook.id, new_title)
        assert result is True


class TestSourceOperations:
    """Test source management operations."""

    def test_add_url_source(self, client, test_notebook):
        """Test adding a URL source."""
        url = "https://en.wikipedia.org/wiki/Artificial_intelligence"
        source = client.add_url_source(test_notebook.id, url)

        # May return None if URL is problematic, but usually returns dict
        if source:
            assert "id" in source or isinstance(source, dict)
            print(f"Added URL source: {source}")

    def test_add_text_source(self, client, test_notebook):
        """Test adding a text source."""
        text = """
        # E2E Test Document
        
        This is a test document for end-to-end testing.
        It contains some text content that can be queried.
        
        Key facts:
        - This is a test
        - The year is 2024
        - AI is being tested
        """
        source = client.add_text_source(test_notebook.id, text=text, title="E2E Test Text")

        assert source is not None
        print(f"Added text source: {source}")

    def test_get_notebook_sources(self, client, test_notebook):
        """Test getting sources with types."""
        # Wait for sources to be indexed
        time.sleep(2)

        sources = client.get_notebook_sources_with_types(test_notebook.id)
        assert isinstance(sources, list)
        print(f"Found {len(sources)} sources in test notebook")

    @pytest.mark.skipif(
        not os.environ.get("NOTEBOOKLM_E2E_UPLOAD"),
        reason="Skipping browser upload test. Set NOTEBOOKLM_E2E_UPLOAD=1 to run.",
    )
    def test_upload_file(self, client, test_notebook):
        """Test uploading a file via browser automation."""
        # Create a dummy file
        dummy_path = Path("test_upload.txt")
        dummy_path.write_text("This is a test upload file content.")

        try:
            print(f"Uploading {dummy_path} to {test_notebook.id}...")
            result = client.upload_file(test_notebook.id, str(dummy_path))
            assert result is True
            print("Upload successful")

            # Verify source appears
            time.sleep(5)
            sources = client.get_notebook_sources_with_types(test_notebook.id)
            titles = [s["title"] for s in sources]
            assert "test_upload.txt" in titles

        finally:
            if dummy_path.exists():
                dummy_path.unlink()


class TestQueryOperations:
    """Test notebook query operations."""

    def test_query_notebook(self, client, test_notebook):
        """Test querying a notebook."""
        # Add a source first
        client.add_text_source(
            test_notebook.id,
            text="The capital of France is Paris. Paris is known for the Eiffel Tower.",
            title="France Facts",
        )

        # Wait for indexing
        time.sleep(3)

        # Query
        result = client.query(test_notebook.id, query_text="What is the capital of France?")

        assert result is not None
        assert "answer" in result
        assert "Paris" in result["answer"] or "paris" in result["answer"].lower()
        print(f"Query answer: {result['answer'][:100]}...")


# TestStudioOperations and TestResearchOperations removed as methods are not implemented yet


class TestCLIIntegration:
    """Test CLI commands work correctly."""

    def test_cli_help(self):
        """Test CLI help command."""
        import subprocess

        result = subprocess.run(["nlm", "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "notebook" in result.stdout.lower()

    def test_cli_version(self):
        """Test CLI version command."""
        import subprocess

        result = subprocess.run(["nlm", "--version"], capture_output=True, text=True)
        assert result.returncode == 0
        # Check version is present (don't hardcode - version changes)
        assert "notebooklm" in result.stdout.lower() or "0." in result.stdout


class TestMCPIntegration:
    """Test MCP server integration."""

    def test_mcp_help(self):
        """Test MCP help command."""
        import subprocess

        result = subprocess.run(["notebooklm-mcp", "--help"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "transport" in result.stdout.lower()
