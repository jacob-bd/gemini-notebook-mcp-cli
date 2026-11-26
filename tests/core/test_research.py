#!/usr/bin/env python3
"""Tests for ResearchMixin."""

from unittest.mock import MagicMock, patch

import pytest

from notebooklm_tools.core.base import BaseClient
from notebooklm_tools.core.errors import RPCError
from notebooklm_tools.core.research import ResearchMixin


class TestResearchMixinImport:
    """Test that ResearchMixin can be imported correctly."""

    def test_research_mixin_import(self):
        """Test that ResearchMixin can be imported."""
        assert ResearchMixin is not None

    def test_research_mixin_inherits_base(self):
        """Test that ResearchMixin inherits from BaseClient."""
        assert issubclass(ResearchMixin, BaseClient)

    def test_research_mixin_has_methods(self):
        """Test that ResearchMixin has expected methods."""
        expected_methods = [
            "start_research",
            "poll_research",
            "import_research_sources",
            "_parse_research_sources",
        ]
        for method in expected_methods:
            assert hasattr(ResearchMixin, method), f"Missing method: {method}"


class TestResearchMixinMethods:
    """Test ResearchMixin method behavior."""

    def test_start_research_validates_source(self):
        """Test that start_research validates source parameter."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")

        with pytest.raises(ValueError, match="Invalid source"):
            mixin.start_research("notebook-id", "query", source="invalid")

    def test_start_research_validates_mode(self):
        """Test that start_research validates mode parameter."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")

        with pytest.raises(ValueError, match="Invalid mode"):
            mixin.start_research("notebook-id", "query", mode="invalid")

    def test_start_research_validates_deep_with_drive(self):
        """Test that start_research rejects deep mode with drive source."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")

        with pytest.raises(ValueError, match="Deep Research only supports Web"):
            mixin.start_research("notebook-id", "query", source="drive", mode="deep")

    def test_parse_research_sources_handles_empty(self):
        """Test that _parse_research_sources handles empty input."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin._parse_research_sources([])

        assert result == []

    def test_parse_research_sources_handles_none_input(self):
        """Test that _parse_research_sources handles non-list input."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin._parse_research_sources(None)

        assert result == []

    def test_import_research_sources_returns_empty_for_no_sources(self):
        """Test that import_research_sources returns empty for no sources."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")

        result = mixin.import_research_sources("notebook-id", "task-id", [])

        assert result == []

    def test_import_rpc_has_no_auth_or_ambiguous_server_replay(self):
        """An import mutation must not use the generic read-only retry pipeline."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")
        sources = [{"url": "https://example.org", "title": "Synthetic", "result_type": 1}]

        with (
            patch.object(mixin, "get_notebook_sources_with_types", return_value=[], create=True),
            patch.object(mixin, "_call_rpc", return_value=[[]]) as rpc,
        ):
            mixin.import_research_sources("notebook-id", "task-id", sources)

        assert rpc.call_count == 1
        kwargs = rpc.call_args.kwargs
        assert kwargs["retry_server_errors"] is False
        assert kwargs["_retry"] is True
        assert kwargs["_deep_retry"] is True

    @pytest.mark.parametrize("code", [3, 9])
    def test_import_ambiguous_rpc_never_confirms_unrelated_source(self, code):
        """An unrelated new source cannot prove this task's import succeeded."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")
        sources = [{"url": "https://example.org", "title": "Synthetic", "result_type": 1}]
        with (
            patch.object(
                mixin,
                "get_notebook_sources_with_types",
                return_value=[{"id": "unrelated-new-source"}],
                create=True,
            ) as inventory,
            patch.object(
                mixin,
                "_call_rpc",
                side_effect=RPCError("provider outcome unknown", error_code=code),
            ) as rpc,
            pytest.raises(RPCError),
        ):
            mixin.import_research_sources("notebook-id", "original-task-id", sources)
        rpc.assert_called_once()
        inventory.assert_not_called()


class TestPollResearchMultiTaskFallback:
    """Test Issue #106: poll_research should not return None for multi-task notebooks."""

    def _build_task_data(self, task_id, query, status_code=2, mode=1):
        """Build a mock task_data list as returned by the API.

        status_code: 1=in_progress, 2=completed, 6=imported
        mode: 1=fast, 5=deep
        """
        return [
            task_id,
            [None, [query, 1], mode, [[], "summary"], status_code],
        ]

    @patch.object(ResearchMixin, "_get_client")
    @patch.object(ResearchMixin, "_build_request_body", return_value="body")
    @patch.object(ResearchMixin, "_build_url", return_value="http://test")
    @patch.object(ResearchMixin, "_parse_response")
    @patch.object(ResearchMixin, "_extract_rpc_result")
    def test_multi_task_mutated_id_returns_most_recent(
        self, mock_extract, mock_parse, mock_url, mock_body, mock_get_client
    ):
        """When target_task_id doesn't match any task in a multi-task notebook,
        poll_research should return the most recent task, not None."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_get_client.return_value.post.return_value = mock_response

        # Simulate 2 tasks: old fast + mutated deep
        mock_extract.return_value = [
            self._build_task_data("fast-task-id", "fast query", status_code=2),
            self._build_task_data("mutated-deep-id", "deep query", status_code=2, mode=5),
        ]

        result = mixin.poll_research("nb-1", target_task_id="original-deep-id")

        # Should NOT return None — should fall back to the most recent task
        assert result is not None
        assert result["task_id"] == "fast-task-id"

    @patch.object(ResearchMixin, "_get_client")
    @patch.object(ResearchMixin, "_build_request_body", return_value="body")
    @patch.object(ResearchMixin, "_build_url", return_value="http://test")
    @patch.object(ResearchMixin, "_parse_response")
    @patch.object(ResearchMixin, "_extract_rpc_result")
    def test_multi_task_prefers_in_progress(
        self, mock_extract, mock_parse, mock_url, mock_body, mock_get_client
    ):
        """When multiple tasks exist and target_task_id doesn't match,
        an in-progress task should be preferred over a completed one."""
        mixin = ResearchMixin(cookies={"test": "cookie"}, csrf_token="test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_get_client.return_value.post.return_value = mock_response

        # Simulate: completed fast task + in-progress deep task
        mock_extract.return_value = [
            self._build_task_data("fast-task-id", "fast query", status_code=2),
            self._build_task_data("deep-task-id", "deep query", status_code=1, mode=5),
        ]

        result = mixin.poll_research("nb-1", target_task_id="original-deep-id")

        assert result is not None
        assert result["task_id"] == "deep-task-id"
        assert result["status"] == "in_progress"
