"""Tests for services.research module."""

from unittest.mock import MagicMock, patch

import pytest

from notebooklm_tools.core.errors import RPCDriftError, RPCError
from notebooklm_tools.services import research as research_service
from notebooklm_tools.services.errors import ServiceError, ValidationError
from notebooklm_tools.services.research import (
    annotate_cited_sources,
    import_research,
    poll_research,
    start_research,
)


@pytest.fixture
def mock_client():
    return MagicMock()


class _FakeClock:
    """Deterministic stand-in for the `time` module: sleeping advances the clock."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock():
    clock = _FakeClock()
    with patch("notebooklm_tools.services.research.time", clock):
        yield clock


class TestStartResearch:
    """Test start_research service function."""

    def test_successful_start(self, mock_client):
        mock_client.start_research.return_value = {
            "task_id": "task-123",
            "notebook_id": "nb-1",
        }

        result = start_research(mock_client, "nb-1", "quantum computing")

        assert result["task_id"] == "task-123"
        assert result["query"] == "quantum computing"
        assert result["source"] == "web"
        assert result["mode"] == "fast"

    def test_invalid_source_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Invalid source"):
            start_research(mock_client, "nb-1", "query", source="twitter")

    def test_invalid_mode_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Invalid mode"):
            start_research(mock_client, "nb-1", "query", mode="ultra")

    def test_deep_drive_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="only available for web"):
            start_research(mock_client, "nb-1", "query", source="drive", mode="deep")

    def test_empty_query_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Query is required"):
            start_research(mock_client, "nb-1", "")

    def test_falsy_result_raises_service_error(self, mock_client):
        mock_client.start_research.return_value = None
        with pytest.raises(ServiceError, match="no data"):
            start_research(mock_client, "nb-1", "query")

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.start_research.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to start research"):
            start_research(mock_client, "nb-1", "query")

    def test_rpc_error_provides_user_friendly_message(self, mock_client):
        """Issue #98: transient DeepResearchErrorDetail should give actionable message."""
        mock_client.start_research.side_effect = RPCError(
            "API error (code 3): DeepResearchErrorDetail",
            error_code=3,
            detail_type="type.googleapis.com/google.internal.labs.tailwind.orchestration.v1.DeepResearchErrorDetail",
            detail_data=[4],
        )
        with pytest.raises(ServiceError) as exc_info:
            start_research(mock_client, "nb-1", "quantum computing", mode="deep")

        assert "error code 3" in exc_info.value.user_message
        assert "DeepResearchErrorDetail" in exc_info.value.user_message
        assert "transient" in exc_info.value.user_message.lower()
        assert "--mode fast" in exc_info.value.user_message

    def test_rpc_error_extracts_short_detail_name(self, mock_client):
        """The service should show only the short detail name, not full type URL."""
        mock_client.start_research.side_effect = RPCError(
            "test",
            error_code=7,
            detail_type="type.googleapis.com/some.long.package.SpecificErrorDetail",
        )
        with pytest.raises(ServiceError) as exc_info:
            start_research(mock_client, "nb-1", "query")

        # Should use short name only
        assert "SpecificErrorDetail" in exc_info.value.user_message
        assert "type.googleapis.com" not in exc_info.value.user_message

    def test_rpc_error_not_swallowed_as_generic(self, mock_client):
        """RPCError must NOT be caught by the generic Exception handler."""
        mock_client.start_research.side_effect = RPCError(
            "API error (code 3)",
            error_code=3,
        )
        with pytest.raises(ServiceError) as exc_info:
            start_research(mock_client, "nb-1", "query")

        # Should mention method-specific error code, not generic "Failed to start research"
        assert "error code 3" in str(exc_info.value)

    def test_drift_error_propagates_verbatim(self, mock_client):
        """RPCDriftError must be wrapped in ServiceError but preserve its message."""
        mock_client.start_research.side_effect = RPCDriftError("Ljjv0c", ["QA9ei"])
        with pytest.raises(ServiceError) as exc_info:
            start_research(mock_client, "nb-1", "query")
        assert "Ljjv0c" in exc_info.value.user_message
        assert "NOTEBOOKLM_RPC_OVERRIDES" in exc_info.value.user_message

    def test_drive_fast_works(self, mock_client):
        mock_client.start_research.return_value = {"task_id": "t-1"}

        result = start_research(mock_client, "nb-1", "query", source="drive", mode="fast")

        assert result["source"] == "drive"
        assert result["mode"] == "fast"


class TestPollResearch:
    """Test poll_research service function."""

    def test_completed_status(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "task-1",
            "sources": [{"title": "Source A"}],
            "report": "Research complete.",
        }

        result = poll_research(mock_client, "nb-1")

        assert result["status"] == "completed"
        assert result["sources_found"] == 1
        assert result["message"] is not None

    def test_no_research_returns_empty(self, mock_client):
        mock_client.poll_research.return_value = None

        result = poll_research(mock_client, "nb-1")

        assert result["status"] == "no_research"
        assert result["sources_found"] == 0

    def test_compact_truncates_report(self, mock_client):
        long_report = "x" * 1000
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "t-1",
            "sources": [],
            "report": long_report,
        }

        result = poll_research(mock_client, "nb-1", compact=True)

        assert len(result["report"]) < 600
        assert "[truncated]" in result["report"]

    def test_compact_limits_sources(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "t-1",
            "sources": [{"title": f"Source {i}"} for i in range(20)],
            "report": "",
        }

        result = poll_research(mock_client, "nb-1", compact=True)

        assert len(result["sources"]) == 6  # 5 + note
        assert "more sources" in str(result["sources"][-1])

    def test_completed_status_marks_cited_sources(self, mock_client):
        report = (
            "The report relies on the second source [1].\n\n"
            "1. Cited Paper, [https://example.com/cited](https://example.com/cited)"
        )
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "t-1",
            "sources": [
                {"index": 0, "title": "Uncited", "url": "https://example.com/uncited"},
                {"index": 1, "title": "Cited Paper", "url": "https://example.com/cited"},
            ],
            "report": report,
        }

        result = poll_research(mock_client, "nb-1", compact=False)

        assert result["sources"][0]["cited"] is False
        assert result["sources"][1]["cited"] is True

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.poll_research.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to poll"):
            poll_research(mock_client, "nb-1")

    def test_single_check_default(self, mock_client):
        """Default max_wait=0 does a single check and returns immediately."""
        mock_client.poll_research.return_value = {
            "status": "in_progress",
            "task_id": "task-1",
            "sources": [],
            "report": "",
        }

        result = poll_research(mock_client, "nb-1")

        assert result["status"] == "in_progress"
        assert mock_client.poll_research.call_count == 1

    @patch("notebooklm_tools.services.research.time")
    def test_blocking_polls_until_completed(self, mock_time, mock_client):
        """With max_wait > 0, polls repeatedly until status is completed."""
        # Simulate monotonic clock advancing by poll_interval each call
        mock_time.monotonic.side_effect = [0, 0, 5, 5, 10]
        mock_time.sleep = MagicMock()

        mock_client.poll_research.side_effect = [
            {"status": "in_progress", "task_id": "t-1", "sources": [], "report": ""},
            {
                "status": "completed",
                "task_id": "t-1",
                "sources": [{"title": "A"}],
                "report": "Done",
            },
        ]

        result = poll_research(mock_client, "nb-1", poll_interval=5, max_wait=30)

        assert result["status"] == "completed"
        assert mock_client.poll_research.call_count == 2
        mock_time.sleep.assert_called_once_with(5)

    @patch("notebooklm_tools.services.research.time")
    def test_blocking_respects_timeout(self, mock_time, mock_client):
        """Polling stops and returns in_progress when max_wait is exceeded."""
        # monotonic calls: [deadline calc, remaining check after poll]
        # deadline = 0 + 10 = 10; remaining = 10 - 11 = -1 → break
        mock_time.monotonic.side_effect = [0, 11]
        mock_time.sleep = MagicMock()

        mock_client.poll_research.return_value = {
            "status": "in_progress",
            "task_id": "t-1",
            "sources": [],
            "report": "",
        }

        result = poll_research(mock_client, "nb-1", poll_interval=5, max_wait=10)

        assert result["status"] == "in_progress"
        assert mock_client.poll_research.call_count == 1
        mock_time.sleep.assert_not_called()

    @patch("notebooklm_tools.services.research.time")
    def test_blocking_sleep_clamped_to_remaining(self, mock_time, mock_client):
        """Sleep duration is clamped to remaining time when less than poll_interval."""
        # monotonic calls: [deadline calc, remaining after poll 1, remaining after poll 2]
        # deadline = 0 + 8 = 8; remaining = 8 - 5 = 3 → sleep(min(5,3)=3);
        # remaining = 8 - 9 = -1 → break
        mock_time.monotonic.side_effect = [0, 5, 9]
        mock_time.sleep = MagicMock()

        mock_client.poll_research.side_effect = [
            {"status": "in_progress", "task_id": "t-1", "sources": [], "report": ""},
            {"status": "in_progress", "task_id": "t-1", "sources": [], "report": ""},
        ]

        result = poll_research(mock_client, "nb-1", poll_interval=5, max_wait=8)

        assert result["status"] == "in_progress"
        assert mock_client.poll_research.call_count == 2
        # Sleep should be clamped to remaining (3), not full poll_interval (5)
        mock_time.sleep.assert_called_once_with(3)

    @patch("notebooklm_tools.services.research.time")
    def test_blocking_no_research_returns_immediately(self, mock_time, mock_client):
        """If no research is found, returns immediately even with max_wait > 0."""
        mock_time.monotonic.side_effect = [0]
        mock_time.sleep = MagicMock()

        mock_client.poll_research.return_value = None

        result = poll_research(mock_client, "nb-1", max_wait=300)

        assert result["status"] == "no_research"
        assert mock_client.poll_research.call_count == 1
        mock_time.sleep.assert_not_called()

    # --- Issue #346: first poll right after `research start` can be empty -------------

    _NO_RESEARCH = {"status": "no_research", "message": "No active research found"}
    _IN_PROGRESS = {"status": "in_progress", "task_id": "t-1", "sources": [], "report": ""}
    _COMPLETED = {
        "status": "completed",
        "task_id": "t-1",
        "sources": [{"title": "A", "url": "https://a.com", "result_type": 1}],
        "report": "Done",
    }

    def test_empty_first_poll_with_task_id_keeps_waiting(self, mock_client, fake_clock):
        """A just-started task may not be visible yet; keep polling instead of giving up."""
        mock_client.poll_research.side_effect = [
            self._NO_RESEARCH,
            self._IN_PROGRESS,
            self._COMPLETED,
        ]

        result = poll_research(mock_client, "nb-1", task_id="t-1", poll_interval=10, max_wait=300)

        assert result["status"] == "completed"
        assert mock_client.poll_research.call_count == 3
        # Short retry while the task is not visible, then the normal poll_interval.
        assert fake_clock.sleeps == [research_service.NO_RESEARCH_RETRY_INTERVAL, 10]

    def test_auto_import_runs_after_empty_first_poll(self, mock_client, fake_clock):
        """Regression for #346: auto_import must still import when the first poll is empty."""
        mock_client.poll_research.side_effect = [
            self._NO_RESEARCH,
            self._COMPLETED,  # poll loop sees it complete
            self._COMPLETED,  # import_research re-fetches the task
        ]
        mock_client.import_research_sources.return_value = [{"title": "A"}]

        result = poll_research(
            mock_client, "nb-1", task_id="t-1", poll_interval=10, max_wait=300, auto_import=True
        )

        assert result["status"] == "completed"
        assert result["imported"] is True
        mock_client.import_research_sources.assert_called_once()

    def test_task_that_never_appears_stops_after_grace_not_max_wait(self, mock_client, fake_clock):
        """A task that never shows up must not make the caller wait out the full max_wait."""
        mock_client.poll_research.return_value = self._NO_RESEARCH

        result = poll_research(mock_client, "nb-1", task_id="t-1", max_wait=900)

        assert result["status"] == "no_research"
        assert sum(fake_clock.sleeps) == research_service.NO_RESEARCH_GRACE_SECONDS
        assert fake_clock.now < 900

    def test_grace_is_capped_by_max_wait(self, mock_client, fake_clock):
        """The grace window never extends past the caller's own max_wait."""
        mock_client.poll_research.return_value = self._NO_RESEARCH

        result = poll_research(mock_client, "nb-1", task_id="t-1", max_wait=20)

        assert result["status"] == "no_research"
        assert sum(fake_clock.sleeps) == 20

    def test_empty_poll_returns_immediately_when_not_blocking(self, mock_client, fake_clock):
        """max_wait=0 is a single check: no grace period, no sleeping."""
        mock_client.poll_research.return_value = self._NO_RESEARCH

        result = poll_research(mock_client, "nb-1", task_id="t-1", max_wait=0)

        assert result["status"] == "no_research"
        assert mock_client.poll_research.call_count == 1
        assert fake_clock.sleeps == []

    def test_grace_can_be_disabled(self, mock_client, fake_clock):
        mock_client.poll_research.return_value = self._NO_RESEARCH

        result = poll_research(
            mock_client, "nb-1", task_id="t-1", max_wait=300, no_research_grace=0
        )

        assert result["status"] == "no_research"
        assert mock_client.poll_research.call_count == 1
        assert fake_clock.sleeps == []

    def test_empty_poll_without_task_id_returns_immediately(self, mock_client, fake_clock):
        """With no task ID there is nothing we just started, so there is nothing to wait for."""
        mock_client.poll_research.return_value = self._NO_RESEARCH

        result = poll_research(mock_client, "nb-1", max_wait=300)

        assert result["status"] == "no_research"
        assert mock_client.poll_research.call_count == 1
        assert fake_clock.sleeps == []

    def test_none_result_with_task_id_also_waits(self, mock_client, fake_clock):
        """A bare None from the client is treated the same as a no_research status."""
        mock_client.poll_research.side_effect = [None, self._COMPLETED]

        result = poll_research(mock_client, "nb-1", task_id="t-1", max_wait=300)

        assert result["status"] == "completed"
        assert mock_client.poll_research.call_count == 2

    def test_completed_status_includes_next_action(self, mock_client):
        """When status is completed, the response includes a next_action hint
        telling the caller exactly which tool to invoke next. Critical for
        LLM agents so they don't leave the notebook empty.
        """
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "task-xyz",
            "sources": [{"title": "A"}],
            "report": "Done",
        }

        result = poll_research(mock_client, "nb-1")

        assert result["status"] == "completed"
        assert result.get("next_action") is not None
        assert "research_import" in result["next_action"]
        assert "task-xyz" in result["next_action"]

    def test_in_progress_status_has_no_next_action(self, mock_client):
        """next_action is only set when research is complete."""
        mock_client.poll_research.return_value = {
            "status": "in_progress",
            "task_id": "task-1",
            "sources": [],
            "report": "",
        }

        result = poll_research(mock_client, "nb-1")

        assert result["status"] == "in_progress"
        assert result.get("next_action") is None

    def test_auto_import_calls_import_when_completed(self, mock_client):
        """auto_import=True triggers import_research automatically on completion."""
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "task-xyz",
            "sources": [{"title": "A", "url": "https://a.com", "result_type": 1}],
            "report": "Done",
        }
        mock_client.import_research_sources.return_value = [{"title": "A"}]

        result = poll_research(mock_client, "nb-1", auto_import=True)

        assert result["status"] == "completed"
        assert result.get("imported") is True
        mock_client.import_research_sources.assert_called_once()

    def test_auto_import_failure_is_visible_without_retry(self, mock_client):
        """Completed research must not conceal an uncertain source import."""
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "task-xyz",
            "sources": [{"title": "A", "url": "https://example.org"}],
            "report": "Done",
        }
        mock_client.import_research_sources.side_effect = RuntimeError("private details")

        result = poll_research(mock_client, "nb-1", auto_import=True)

        assert result["status"] == "completed"
        assert result["task_id"] == "task-xyz"
        assert result["imported"] is False
        assert "import_error" in result
        assert "private details" not in result["import_error"]
        assert "not confirmed" in result["message"]
        assert "reconcile" in result["next_action"]
        mock_client.import_research_sources.assert_called_once()

    def test_auto_import_false_does_not_import(self, mock_client):
        """auto_import=False (default) never calls import."""
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "task-xyz",
            "sources": [{"title": "A"}],
            "report": "Done",
        }

        poll_research(mock_client, "nb-1", auto_import=False)

        mock_client.import_research_sources.assert_not_called()

    def test_auto_import_skipped_when_not_completed(self, mock_client):
        """auto_import=True does not import if research is still in_progress."""
        mock_client.poll_research.return_value = {
            "status": "in_progress",
            "task_id": "task-1",
            "sources": [],
            "report": "",
        }

        result = poll_research(mock_client, "nb-1", auto_import=True)

        assert result.get("imported") is not True
        mock_client.import_research_sources.assert_not_called()


class TestImportResearch:
    """Test import_research service function."""

    def test_import_all_sources(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
        }
        mock_client.import_research_sources.return_value = [
            {"title": "A"},
            {"title": "B"},
            {"title": "C"},
        ]

        result = import_research(mock_client, "nb-1", "task-1")

        assert result["imported_count"] == 3

        # Verify it passes the requested task ID if no mutated ID is returned
        call_args = mock_client.import_research_sources.call_args
        assert call_args.kwargs["task_id"] == "task-1"

    def test_import_resolves_mutated_task_id(self, mock_client):
        """Verify that deep research task_id mutations are handled."""
        mock_client.poll_research.return_value = {
            "status": "completed",
            "task_id": "mutated-task-999",
            "sources": [{"title": "A"}],
        }
        mock_client.import_research_sources.return_value = [{"title": "A"}]

        import_research(mock_client, "nb-1", "task-1")

        call_args = mock_client.import_research_sources.call_args
        # Should pass the mutated task ID from poll_research, not the request task_id
        assert call_args.kwargs["task_id"] == "mutated-task-999"

    def test_import_selected_indices(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
        }
        mock_client.import_research_sources.return_value = [{"title": "B"}]

        import_research(mock_client, "nb-1", "task-1", source_indices=[1])

        # Verify the correct source was passed
        call_args = mock_client.import_research_sources.call_args
        assert call_args.kwargs["sources"] == [{"title": "B"}]

    def test_import_cited_only_resolves_bibliography_urls(self, mock_client):
        sources = [
            {"index": 0, "title": "Unused", "url": "https://example.com/unused"},
            {"index": 1, "title": "Also unused", "url": "https://example.com/also-unused"},
            {"index": 2, "title": "Cited", "url": "https://example.com/cited"},
        ]
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": sources,
            "report": (
                "NotebookLM cites bibliography item one [1].\n\n"
                "1. Cited, [https://example.com/cited](https://example.com/cited)"
            ),
        }
        mock_client.import_research_sources.return_value = [{"title": "Cited"}]

        import_research(mock_client, "nb-1", "task-1", cited_only=True)

        call_args = mock_client.import_research_sources.call_args
        assert call_args.kwargs["sources"] == [sources[2]]

    def test_import_cited_only_overrides_source_indices(self, mock_client):
        sources = [
            {"index": 0, "title": "Manual pick", "url": "https://example.com/manual"},
            {"index": 1, "title": "Cited", "url": "https://example.com/cited"},
        ]
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": sources,
            "report": (
                "The report cites the second source [1].\n\n"
                "1. Cited, [https://example.com/cited](https://example.com/cited)"
            ),
        }
        mock_client.import_research_sources.return_value = [{"title": "Cited"}]

        import_research(
            mock_client,
            "nb-1",
            "task-1",
            source_indices=[0],
            cited_only=True,
        )

        call_args = mock_client.import_research_sources.call_args
        assert call_args.kwargs["sources"] == [sources[1]]

    def test_import_cited_only_falls_back_to_all_sources_without_citations(self, mock_client):
        sources = [
            {"index": 0, "title": "A", "url": "https://example.com/a"},
            {"index": 1, "title": "B", "url": "https://example.com/b"},
        ]
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": sources,
            "report": "The report has no citation markers or bibliography.",
        }
        mock_client.import_research_sources.return_value = [{"title": "A"}, {"title": "B"}]

        import_research(mock_client, "nb-1", "task-1", cited_only=True)

        call_args = mock_client.import_research_sources.call_args
        assert call_args.kwargs["sources"] == sources

    def test_annotate_cited_sources_skips_duplicate_title_false_positive(self):
        sources = [
            {
                "index": 0,
                "title": "Embedding-Based Context-Aware Reranker",
                "url": "https://example.com/paper-v1",
            },
            {
                "index": 1,
                "title": "Embedding-Based Context-Aware Reranker",
                "url": "https://example.com/paper-v2",
            },
        ]
        report = (
            "Embedding-Based Context-Aware Reranker improves retrieval [1].\n\n"
            "1. Embedding-Based Context-Aware Reranker, "
            "[https://example.com/paper-v2](https://example.com/paper-v2)"
        )

        annotated = annotate_cited_sources(sources, report)

        assert annotated[0]["cited"] is False
        assert annotated[1]["cited"] is True

    def test_no_research_raises_service_error(self, mock_client):
        mock_client.poll_research.return_value = {"status": "no_research"}
        with pytest.raises(ServiceError, match="not found"):
            import_research(mock_client, "nb-1", "task-missing")

    def test_no_sources_raises_service_error(self, mock_client):
        mock_client.poll_research.return_value = {"status": "completed", "sources": []}
        with pytest.raises(ServiceError, match="No sources"):
            import_research(mock_client, "nb-1", "task-1")

    def test_invalid_indices_raises_validation_error(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}],
        }
        with pytest.raises(ValidationError, match="indices"):
            import_research(mock_client, "nb-1", "task-1", source_indices=[99])

    def test_import_api_error_raises_service_error(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}],
        }
        mock_client.import_research_sources.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to import"):
            import_research(mock_client, "nb-1", "task-1")

    def test_falsy_import_result_raises_service_error(self, mock_client):
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}],
        }
        mock_client.import_research_sources.return_value = None
        with pytest.raises(ServiceError, match="no data"):
            import_research(mock_client, "nb-1", "task-1")

    def test_import_passes_custom_timeout(self, mock_client):
        """Verify that a custom timeout is forwarded to the client."""
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}],
        }
        mock_client.import_research_sources.return_value = [{"title": "A"}]

        import_research(mock_client, "nb-1", "task-1", timeout=600.0)

        call_kwargs = mock_client.import_research_sources.call_args.kwargs
        assert call_kwargs["timeout"] == 600.0

    def test_import_uses_default_timeout(self, mock_client):
        """Verify that the default 300s timeout is used when none specified."""
        mock_client.poll_research.return_value = {
            "status": "completed",
            "sources": [{"title": "A"}],
        }
        mock_client.import_research_sources.return_value = [{"title": "A"}]

        import_research(mock_client, "nb-1", "task-1")

        call_kwargs = mock_client.import_research_sources.call_args.kwargs
        assert call_kwargs["timeout"] == 300.0
