"""End-to-end tests for MCP Server Tools.

Tests the consolidated MCP tools against the real NotebookLM API.

Run with: NOTEBOOKLM_E2E=1 pytest tests/test_mcp_e2e.py -v
"""

import asyncio
import contextlib
import os
import time

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
def mcp_tools():
    """Import all MCP tools and reset client for fresh auth."""
    # Reset cached client to pick up fresh auth tokens
    from notebooklm_tools.mcp.tools._utils import reset_client

    reset_client()

    from notebooklm_tools.mcp.tools import (
        auth,
        chat,
        downloads,
        notebooks,
        research,
        sharing,
        sources,
        studio,
    )

    return {
        "notebooks": notebooks,
        "sources": sources,
        "studio": studio,
        "downloads": downloads,
        "sharing": sharing,
        "research": research,
        "chat": chat,
        "auth": auth,
    }


@pytest.fixture(scope="module")
def test_notebook(mcp_tools):
    """Create a test notebook, cleanup after."""
    result = mcp_tools["notebooks"].notebook_create(title=f"MCP E2E Test {int(time.time())}")
    assert result["status"] == "success", f"Failed to create: {result}"
    notebook_id = result["notebook_id"]

    yield notebook_id

    # Cleanup
    with contextlib.suppress(Exception):
        mcp_tools["notebooks"].notebook_delete(notebook_id, confirm=True)


class TestMCPNotebookTools:
    """Test notebook MCP tools."""

    def test_notebook_list(self, mcp_tools):
        """Test listing notebooks."""
        result = mcp_tools["notebooks"].notebook_list()
        assert result["status"] == "success"
        assert "notebooks" in result
        print(f"Found {result['count']} notebooks")

    def test_notebook_create_rename_delete(self, mcp_tools):
        """Test full notebook lifecycle."""
        # Create
        result = mcp_tools["notebooks"].notebook_create(title="MCP Delete Test")
        assert result["status"] == "success"
        notebook_id = result["notebook_id"]

        # Rename
        result = mcp_tools["notebooks"].notebook_rename(notebook_id, "MCP Renamed Test")
        assert result["status"] == "success"

        # Delete
        result = mcp_tools["notebooks"].notebook_delete(notebook_id, confirm=True)
        assert result["status"] == "success"

    def test_notebook_describe(self, mcp_tools, test_notebook):
        """Test notebook AI summary."""
        # First add a source
        mcp_tools["sources"].source_add(
            notebook_id=test_notebook,
            source_type="text",
            text="Artificial Intelligence (AI) is transforming technology.",
            title="AI Overview",
        )
        time.sleep(3)  # Wait for indexing

        result = mcp_tools["notebooks"].notebook_describe(test_notebook)
        # May fail if no sources, but should not error
        assert "status" in result


class TestMCPConsolidatedSourceAdd:
    """Test consolidated source_add tool."""

    def test_source_add_text(self, mcp_tools, test_notebook):
        """Test adding text source."""
        result = mcp_tools["sources"].source_add(
            notebook_id=test_notebook,
            source_type="text",
            text="This is a test document for MCP E2E testing. Key fact: Python is great.",
            title="MCP Test Text",
        )
        assert result["status"] == "success"
        print(f"Added text source: {result}")

    def test_source_add_url(self, mcp_tools, test_notebook):
        """Test adding URL source."""
        result = mcp_tools["sources"].source_add(
            notebook_id=test_notebook,
            source_type="url",
            url="https://en.wikipedia.org/wiki/Claude_(language_model)",
        )
        # URL may fail for various reasons, but should have a status
        assert "status" in result
        print(f"URL source result: {result}")

    def test_source_add_invalid_type(self, mcp_tools, test_notebook):
        """Test error handling for invalid source type."""
        result = mcp_tools["sources"].source_add(
            notebook_id=test_notebook, source_type="invalid_type", text="test"
        )
        assert result["status"] == "error"
        assert "Unknown source_type" in result["error"]


class TestMCPQueryTools:
    """Test query/chat MCP tools."""

    def test_notebook_query(self, mcp_tools, test_notebook):
        """Test querying notebook."""
        # Add content first
        mcp_tools["sources"].source_add(
            notebook_id=test_notebook,
            source_type="text",
            text="The speed of light is approximately 299,792 kilometers per second.",
            title="Physics Facts",
        )
        time.sleep(3)

        result = asyncio.run(
            mcp_tools["chat"].notebook_query(
                notebook_id=test_notebook, query="What is the speed of light?"
            )
        )

        assert result["status"] == "success"
        assert "answer" in result
        # Check the answer contains relevant content
        answer = result["answer"].lower()
        assert "299" in answer or "light" in answer or "speed" in answer
        print(f"Query answer: {result['answer'][:200]}...")


class TestMCPConsolidatedStudioCreate:
    """Test consolidated studio_create tool."""

    def test_studio_create_without_confirm(self, mcp_tools, test_notebook):
        """Test studio_create returns pending confirmation."""
        result = mcp_tools["studio"].studio_create(
            notebook_id=test_notebook,
            artifact_type="audio",
            confirm=False,  # Should return pending
        )
        assert result["status"] == "pending_confirmation"
        assert "settings" in result
        print(f"Pending confirmation: {result}")

    def test_studio_create_invalid_type(self, mcp_tools, test_notebook):
        """Test error handling for invalid artifact type."""
        result = mcp_tools["studio"].studio_create(
            notebook_id=test_notebook, artifact_type="invalid_type", confirm=True
        )
        assert result["status"] == "error"
        assert "Unknown artifact_type" in result["error"]

    @pytest.mark.skipif(
        not os.environ.get("NOTEBOOKLM_E2E_STUDIO"),
        reason="Skipping studio creation. Set NOTEBOOKLM_E2E_STUDIO=1 to run.",
    )
    def test_studio_create_flashcards(self, mcp_tools, test_notebook):
        """Test creating flashcards (fastest artifact)."""
        # Add source first
        mcp_tools["sources"].source_add(
            notebook_id=test_notebook,
            source_type="text",
            text="Python was created by Guido van Rossum. It was first released in 1991.",
            title="Python History",
        )
        time.sleep(3)

        result = mcp_tools["studio"].studio_create(
            notebook_id=test_notebook, artifact_type="flashcards", difficulty="easy", confirm=True
        )
        assert result["status"] in ("success", "error")
        if result["status"] == "success":
            print(f"Created flashcards: {result}")

    def test_studio_status(self, mcp_tools, test_notebook):
        """Test checking studio status."""
        result = mcp_tools["studio"].studio_status(test_notebook)
        assert result["status"] == "success"
        assert "artifacts" in result
        print(f"Studio has {result['summary']['total']} artifacts")


class TestMCPSharingTools:
    """Test sharing MCP tools."""

    def test_notebook_share_status(self, mcp_tools, test_notebook):
        """Test getting share status."""
        result = mcp_tools["sharing"].notebook_share_status(test_notebook)
        assert result["status"] == "success"
        assert "is_public" in result
        print(f"Sharing status: {result}")

    def test_notebook_share_public_toggle(self, mcp_tools, test_notebook):
        """Test enabling/disabling public link."""
        # Enable
        result = mcp_tools["sharing"].notebook_share_public(test_notebook, is_public=True)
        assert result["status"] == "success"
        assert result["is_public"] is True
        assert "public_link" in result
        print(f"Public link: {result['public_link']}")

        # Disable
        result = mcp_tools["sharing"].notebook_share_public(test_notebook, is_public=False)
        assert result["status"] == "success"
        assert result["is_public"] is False


class TestMCPDownloadTools:
    """Test consolidated download_artifact tool."""

    def test_download_artifact_invalid_type(self, mcp_tools, test_notebook):
        """Test error handling for invalid type."""
        result = mcp_tools["downloads"].download_artifact(
            notebook_id=test_notebook, artifact_type="invalid_type", output_path="test.txt"
        )
        assert result["status"] == "error"
        assert "Unknown artifact_type" in result["error"]

    def test_download_artifact_no_artifact(self, mcp_tools, test_notebook):
        """Test download when no artifact exists."""
        result = mcp_tools["downloads"].download_artifact(
            notebook_id=test_notebook, artifact_type="audio", output_path="test_audio.m4a"
        )
        # Should fail gracefully - no audio exists
        assert result["status"] == "error"


class TestMCPToolRegistry:
    """Test tool registration and structure."""

    def test_all_tools_registered(self):
        """Verify the current consolidated MCP tool surface is registered."""
        from notebooklm_tools.mcp.tools._utils import _tool_registry

        tool_names = {name for name, _ in _tool_registry}

        # Check consolidated tools exist
        assert "download_artifact" in tool_names
        assert "studio_create" in tool_names
        assert "source_add" in tool_names

        print(f"All {len(tool_names)} tools registered: {sorted(tool_names)}")

    def test_old_tools_removed(self):
        """Verify old individual tools are not registered."""
        from notebooklm_tools.mcp.tools._utils import _tool_registry

        tool_names = {name for name, _ in _tool_registry}

        # These old tools should NOT exist
        old_tools = [
            "download_audio",
            "download_video",
            "audio_overview_create",
            "video_overview_create",
            "notebook_add_url",
            "notebook_add_text",
        ]

        for old_tool in old_tools:
            assert old_tool not in tool_names, f"Old tool {old_tool} should be removed"
