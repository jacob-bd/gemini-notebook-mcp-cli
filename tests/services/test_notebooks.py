"""Tests for services.notebooks module."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from notebooklm_tools.services.errors import (
    CreationError,
    NotFoundError,
    ServiceError,
    ValidationError,
)
from notebooklm_tools.services.notebooks import (
    create_notebook,
    delete_notebook,
    describe_notebook,
    get_notebook,
    list_notebooks,
    rename_notebook,
)


@pytest.fixture
def mock_client():
    return MagicMock()


def _make_notebook(**kwargs):
    """Create a mock notebook object with default attrs."""
    defaults = {
        "id": "nb-1",
        "title": "Test Notebook",
        "source_count": 3,
        "url": "https://notebooklm.google.com/notebook/nb-1",
        "ownership": "owned",
        "is_owned": True,
        "is_shared": False,
        "created_at": "2024-01-01",
        "modified_at": "2024-01-02",
        "emoji": "📚",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestListNotebooks:
    """Test list_notebooks service function."""

    def test_returns_notebooks_with_counts(self, mock_client):
        mock_client.list_notebooks.return_value = [
            _make_notebook(id="nb-1", is_owned=True, is_shared=False),
            _make_notebook(id="nb-2", is_owned=True, is_shared=True),
            _make_notebook(id="nb-3", is_owned=False, is_shared=False),
        ]

        result = list_notebooks(mock_client)

        assert result["count"] == 3
        assert result["owned_count"] == 2
        assert result["shared_count"] == 1
        assert result["shared_by_me_count"] == 1
        assert len(result["notebooks"]) == 3

    def test_max_results_truncates(self, mock_client):
        mock_client.list_notebooks.return_value = [_make_notebook(id=f"nb-{i}") for i in range(10)]

        result = list_notebooks(mock_client, max_results=3)

        assert len(result["notebooks"]) == 3
        assert result["count"] == 10  # count reflects total, not truncated

    def test_urls_follow_active_profile_host(self, mock_client, monkeypatch):
        monkeypatch.delenv("NOTEBOOKLM_BASE_URL", raising=False)
        mock_client._base_host = "notebook.google.com"
        mock_client.list_notebooks.return_value = [_make_notebook()]

        result = list_notebooks(mock_client)

        assert result["notebooks"][0]["url"] == "https://notebook.google.com/notebook/nb-1"

    def test_empty_list(self, mock_client):
        mock_client.list_notebooks.return_value = []

        result = list_notebooks(mock_client)

        assert result["count"] == 0
        assert result["notebooks"] == []

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.list_notebooks.side_effect = RuntimeError("API error")
        with pytest.raises(ServiceError, match="Failed to list notebooks"):
            list_notebooks(mock_client)


class TestGetNotebook:
    """Test get_notebook service function."""

    def test_raw_rpc_list_parsed(self, mock_client):
        # Simulate the nested list structure from the API
        mock_client.get_notebook.return_value = [
            [
                "My Notebook",  # title
                [  # sources
                    [["src-1"], "Source A"],
                    [["src-2"], "Source B"],
                ],
                "nb-123",  # id
                "🧠",  # emoji
            ]
        ]

        result = get_notebook(mock_client, "nb-123")

        assert result["notebook_id"] == "nb-123"
        assert result["title"] == "My Notebook"
        assert result["source_count"] == 2
        assert result["sources"][0]["id"] == "src-1"
        assert result["sources"][1]["title"] == "Source B"
        assert result["emoji"] == "🧠"

    def test_source_urls_match_core_metadata_parser(self, mock_client):
        web = [None] * 8
        web[4] = 5  # NotebookLM web source type; untyped slots are not URL provenance.
        web[7] = ["https://example.org/article"]
        youtube = [None] * 8
        youtube[4] = 9
        youtube[5] = ["https://youtu.be/example", "example", "Example channel"]
        mock_client.get_notebook.return_value = [
            [
                "Notebook",
                [
                    [["web"], "Web", web],
                    [["video"], "Video", youtube],
                    [["text"], "Text", []],
                    [["old"], "Legacy"],
                    [["invalid"], "Invalid metadata", "not a list"],
                ],
                "nb-123",
            ]
        ]

        result = get_notebook(mock_client, "nb-123")

        assert [source["url"] for source in result["sources"]] == [
            "https://example.org/article",
            "https://youtu.be/example",
            None,
            None,
            None,
        ]
        mock_client.get_notebook.assert_called_once_with("nb-123")

    def test_dataclass_fallback(self, mock_client):
        mock_client.get_notebook.return_value = _make_notebook(id="nb-42", title="Fallback")

        result = get_notebook(mock_client, "nb-42")

        assert result["notebook_id"] == "nb-42"
        assert result["title"] == "Fallback"
        assert result["emoji"] == "📚"

    def test_dataclass_url_follows_active_profile_host(self, mock_client, monkeypatch):
        monkeypatch.delenv("NOTEBOOKLM_BASE_URL", raising=False)
        mock_client._base_host = "notebook.google.com"
        mock_client.get_notebook.return_value = _make_notebook()

        result = get_notebook(mock_client, "nb-1")

        assert result["url"] == "https://notebook.google.com/notebook/nb-1"

    def test_none_raises_not_found(self, mock_client):
        mock_client.get_notebook.return_value = None
        with pytest.raises(NotFoundError, match="not found"):
            get_notebook(mock_client, "nb-missing")

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.get_notebook.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to get notebook"):
            get_notebook(mock_client, "nb-123")


class TestDescribeNotebook:
    """Test describe_notebook service function."""

    def test_returns_summary_and_topics(self, mock_client):
        mock_client.get_notebook_summary.return_value = {
            "summary": "A great notebook about AI.",
            "suggested_topics": ["machine learning", "neural networks"],
        }

        result = describe_notebook(mock_client, "nb-123")

        assert "AI" in result["summary"]
        assert len(result["suggested_topics"]) == 2

    def test_falsy_result_raises_service_error(self, mock_client):
        mock_client.get_notebook_summary.return_value = None
        with pytest.raises(ServiceError, match="no data"):
            describe_notebook(mock_client, "nb-123")

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.get_notebook_summary.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to get notebook summary"):
            describe_notebook(mock_client, "nb-123")


class TestCreateNotebook:
    """Test create_notebook service function."""

    def test_successful_creation(self, mock_client):
        mock_client.create_notebook.return_value = _make_notebook(id="nb-new", title="New NB")

        result = create_notebook(mock_client, "New NB")

        assert result["notebook_id"] == "nb-new"
        assert result["title"] == "New NB"
        assert "Created" in result["message"]

    def test_created_url_follows_active_profile_host(self, mock_client, monkeypatch):
        monkeypatch.delenv("NOTEBOOKLM_BASE_URL", raising=False)
        mock_client._base_host = "notebook.google.com"
        mock_client.create_notebook.return_value = _make_notebook(id="nb-new")

        result = create_notebook(mock_client, "New NB")

        assert result["url"] == "https://notebook.google.com/notebook/nb-new"

    def test_falsy_result_raises_creation_error(self, mock_client):
        mock_client.create_notebook.return_value = None
        with pytest.raises(CreationError, match="no data"):
            create_notebook(mock_client, "Test")

    def test_api_error_raises_creation_error(self, mock_client):
        mock_client.create_notebook.side_effect = RuntimeError("fail")
        with pytest.raises(CreationError, match="Failed to create notebook"):
            create_notebook(mock_client, "Test")


class TestRenameNotebook:
    """Test rename_notebook service function."""

    def test_successful_rename(self, mock_client):
        mock_client.rename_notebook.return_value = True

        result = rename_notebook(mock_client, "nb-123", "New Title")

        assert result["new_title"] == "New Title"
        assert "Renamed" in result["message"]

    def test_empty_title_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="title"):
            rename_notebook(mock_client, "nb-123", "")

    def test_whitespace_title_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="title"):
            rename_notebook(mock_client, "nb-123", "   ")

    def test_falsy_result_raises_service_error(self, mock_client):
        mock_client.rename_notebook.return_value = None
        with pytest.raises(ServiceError, match="falsy result"):
            rename_notebook(mock_client, "nb-123", "Valid Title")

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.rename_notebook.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to rename notebook"):
            rename_notebook(mock_client, "nb-123", "Valid Title")


class TestDeleteNotebook:
    """Test delete_notebook service function."""

    def test_successful_deletion(self, mock_client):
        mock_client.delete_notebook.return_value = True

        result = delete_notebook(mock_client, "nb-123")

        assert "deleted" in result["message"].lower()

    def test_falsy_result_raises_service_error(self, mock_client):
        mock_client.delete_notebook.return_value = None
        with pytest.raises(ServiceError, match="falsy result"):
            delete_notebook(mock_client, "nb-123")

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.delete_notebook.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to delete notebook"):
            delete_notebook(mock_client, "nb-123")
