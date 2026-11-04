"""Tests for services.chat module."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from notebooklm_tools.core.conversation import QueryRejectedError
from notebooklm_tools.core.data_types import Notebook
from notebooklm_tools.services.chat import (
    _QUERY_TTL_SECONDS,
    _pending_lock,
    _pending_queries,
    configure_chat,
    delete_chat_history,
    query,
    query_start,
    query_status,
)
from notebooklm_tools.services.errors import ServiceError, ValidationError


@pytest.fixture
def mock_client():
    client = MagicMock()
    client._is_enterprise.return_value = False
    return client


class TestQuery:
    """Test query service function."""

    def test_successful_query(self, mock_client):
        mock_client.query.return_value = {
            "answer": "The answer is 42.",
            "conversation_id": "conv-123",
            "sources_used": ["src-1", "src-2"],
            "citations": {1: "src-1", 2: "src-1", 3: "src-2"},
        }

        result = query(mock_client, "nb-123", "What is the meaning?")

        assert result["answer"] == "The answer is 42."
        assert result["question"] == "What is the meaning?"
        assert result["conversation_id"] == "conv-123"
        assert result["sources_used"] == ["src-1", "src-2"]
        assert result["citations"] == {1: "src-1", 2: "src-1", 3: "src-2"}

    def test_empty_query_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Query text is required"):
            query(mock_client, "nb-123", "")

    @patch("notebooklm_tools.services.chat.notebook_service")
    def test_empty_notebook_raises_validation_error(self, mock_notebook_service, mock_client):
        """Querying an empty notebook should raise a ValidationError."""
        mock_notebook_service.get_notebook.return_value = {"source_count": 0}
        with pytest.raises(ValidationError, match="Cannot query an empty notebook"):
            query(mock_client, "nb-123", "question")

    def test_whitespace_query_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Query text is required"):
            query(mock_client, "nb-123", "   ")

    def test_falsy_result_raises_service_error(self, mock_client):
        mock_client.query.return_value = None
        with pytest.raises(ServiceError, match="empty result"):
            query(mock_client, "nb-123", "question")

    @pytest.mark.parametrize("answer", ["", "   ", None])
    def test_empty_answer_raises_service_error(self, mock_client, answer):
        mock_client.query.return_value = {"answer": answer}

        with pytest.raises(ServiceError, match="empty answer"):
            query(mock_client, "nb-123", "question", source_ids=["src-1"])

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.query.side_effect = RuntimeError("timeout")
        with pytest.raises(ServiceError, match="Query failed"):
            query(mock_client, "nb-123", "question")

    @pytest.mark.parametrize(
        ("provider_code", "category", "retryable", "suggested_action"),
        [
            (3, "invalid_argument", False, "check_query_arguments"),
            (5, "not_found", False, "check_notebook_and_source_ids"),
            (8, "resource_exhausted", True, "retry_after_delay"),
            (16, "unauthenticated", False, "run_nlm_login"),
        ],
    )
    def test_query_rejection_has_structured_metadata(
        self,
        mock_client,
        provider_code,
        category,
        retryable,
        suggested_action,
    ):
        mock_client.query.side_effect = QueryRejectedError(provider_code)

        with pytest.raises(ServiceError) as exc_info:
            query(mock_client, "nb-123", "question", source_ids=["src-1"])

        error = exc_info.value
        assert error.provider_code == provider_code
        assert error.category == category
        assert error.retryable is retryable
        assert error.suggested_action == suggested_action
        assert error.debug_code == f"query_{category}"

    def test_invalid_argument_does_not_recommend_reauthentication(self, mock_client):
        mock_client.query.side_effect = QueryRejectedError(3)

        with pytest.raises(ServiceError) as exc_info:
            query(mock_client, "nb-123", "question", source_ids=["missing-source"])

        error = exc_info.value
        assert "invalid" in error.user_message.lower()
        assert "login" not in error.user_message.lower()
        assert "login" not in (error.hint or "").lower()

    def test_source_ids_passed_through(self, mock_client):
        mock_client.query.return_value = {"answer": "ok"}
        query(mock_client, "nb-123", "question", source_ids=["src-1"])
        call_kwargs = mock_client.query.call_args.kwargs
        assert call_kwargs["notebook_id"] == "nb-123"
        assert call_kwargs["query_text"] == "question"
        assert call_kwargs["source_ids"] == ["src-1"]
        assert call_kwargs["conversation_id"] is None
        assert 0 < call_kwargs["timeout"] <= 120.0 + 1e-9

    def test_new_conversation_passed_through(self, mock_client):
        mock_client.query.return_value = {"answer": "ok"}

        query(
            mock_client,
            "nb-123",
            "question",
            source_ids=["src-1"],
            new_conversation=True,
        )

        call_kwargs = mock_client.query.call_args.kwargs
        assert call_kwargs["notebook_id"] == "nb-123"
        assert call_kwargs["query_text"] == "question"
        assert call_kwargs["source_ids"] == ["src-1"]
        assert call_kwargs["conversation_id"] is None
        assert call_kwargs["new_conversation"] is True
        assert 0 < call_kwargs["timeout"] <= 120.0 + 1e-9

    def test_enterprise_source_resolution_uses_enterprise_list(self, mock_client):
        """Whole-notebook Enterprise queries must not call consumer get_notebook."""
        mock_client._is_enterprise.return_value = True
        mock_client.list_notebooks.return_value = [
            Notebook(
                id="nb-123",
                title="Enterprise notebook",
                source_count=1,
                sources=[{"id": "src-1", "title": "Source"}],
            )
        ]
        mock_client.query.return_value = {"answer": "ok"}

        with patch("notebooklm_tools.services.chat.notebook_service.get_notebook") as get_notebook:
            query(mock_client, "nb-123", "question")

        get_notebook.assert_not_called()
        assert mock_client.query.call_args.kwargs["source_ids"] == ["src-1"]

    def test_timeout_passed_through(self, mock_client):
        mock_client.query.return_value = {"answer": "ok"}
        query(mock_client, "nb-123", "question", timeout=30.0)
        call_kwargs = mock_client.query.call_args.kwargs
        assert call_kwargs["notebook_id"] == "nb-123"
        assert call_kwargs["query_text"] == "question"
        assert call_kwargs["source_ids"] is None
        assert call_kwargs["conversation_id"] is None
        assert 0 < call_kwargs["timeout"] <= 30.0 + 1e-9

    @patch("notebooklm_tools.services.chat.notebook_service")
    def test_query_reuses_validated_sources_and_timeout_budget(
        self, mock_notebook_service, mock_client
    ):
        mock_notebook_service.get_notebook.return_value = {
            "source_count": 2,
            "sources": [
                {"id": "src-1", "title": "First"},
                {"id": "src-2", "title": "Second"},
            ],
        }
        mock_client.query.return_value = {"answer": "ok"}

        with patch("notebooklm_tools.services.chat.time.monotonic", return_value=100.0):
            query(mock_client, "nb-123", "question", timeout=45.0)

        mock_notebook_service.get_notebook.assert_called_once_with(
            mock_client, "nb-123", timeout=45.0
        )
        mock_client.query.assert_called_once_with(
            notebook_id="nb-123",
            query_text="question",
            source_ids=["src-1", "src-2"],
            conversation_id=None,
            timeout=45.0,
        )

    def test_read_timeout_has_structured_deadline_error(self, mock_client):
        mock_client.query.side_effect = httpx.ReadTimeout("The read operation timed out")

        with pytest.raises(ServiceError) as exc_info:
            query(mock_client, "nb-123", "question", source_ids=["src-1"], timeout=45.0)

        error = exc_info.value
        assert error.user_message == (
            "NotebookLM did not respond within the configured query timeout."
        )
        assert error.hint == "Retry with a longer timeout, such as 180 seconds."
        assert error.category == "deadline_exceeded"
        assert error.retryable is True
        assert error.suggested_action == "retry_with_longer_timeout"
        assert error.debug_code == "query_deadline_exceeded"


class TestConfigureChat:
    """Test configure_chat service function."""

    def test_successful_default_config(self, mock_client):
        mock_client.configure_chat.return_value = {"status": "ok"}

        result = configure_chat(mock_client, "nb-123")

        assert result["goal"] == "default"
        assert result["response_length"] == "default"
        assert "updated" in result["message"].lower()

    def test_invalid_goal_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Invalid goal"):
            configure_chat(mock_client, "nb-123", goal="invalid")

    def test_custom_goal_without_prompt_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Custom prompt is required"):
            configure_chat(mock_client, "nb-123", goal="custom")

    def test_custom_goal_with_prompt_works(self, mock_client):
        mock_client.configure_chat.return_value = {"status": "ok"}

        result = configure_chat(
            mock_client,
            "nb-123",
            goal="custom",
            custom_prompt="Be a pirate.",
        )

        assert result["goal"] == "custom"

    def test_prompt_too_long_raises_validation_error(self, mock_client):
        long_prompt = "x" * 10_001
        with pytest.raises(ValidationError, match="10000 character"):
            configure_chat(
                mock_client,
                "nb-123",
                goal="custom",
                custom_prompt=long_prompt,
            )

    def test_invalid_response_length_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Invalid response_length"):
            configure_chat(mock_client, "nb-123", response_length="huge")

    def test_learning_guide_goal_works(self, mock_client):
        mock_client.configure_chat.return_value = {"status": "ok"}

        result = configure_chat(mock_client, "nb-123", goal="learning_guide")

        assert result["goal"] == "learning_guide"

    def test_shorter_response_length_works(self, mock_client):
        mock_client.configure_chat.return_value = {"status": "ok"}

        result = configure_chat(mock_client, "nb-123", response_length="shorter")

        assert result["response_length"] == "shorter"

    def test_falsy_result_raises_service_error(self, mock_client):
        mock_client.configure_chat.return_value = None
        with pytest.raises(ServiceError, match="falsy result"):
            configure_chat(mock_client, "nb-123")

    def test_api_error_raises_service_error(self, mock_client):
        mock_client.configure_chat.side_effect = RuntimeError("fail")
        with pytest.raises(ServiceError, match="Failed to configure"):
            configure_chat(mock_client, "nb-123")


class TestDeleteChatHistory:
    """Test delete_chat_history service function."""

    def test_successful_deletion(self, mock_client):
        mock_client.get_conversation_id.return_value = "conv-123"
        mock_client.delete_chat_history.return_value = True

        result = delete_chat_history(mock_client, "nb-123")

        assert result["notebook_id"] == "nb-123"
        assert result["conversation_id"] == "conv-123"
        assert "deleted" in result["message"].lower()
        mock_client.delete_chat_history.assert_called_once_with("nb-123", "conv-123")

    def test_no_history_raises_service_error(self, mock_client):
        mock_client.get_conversation_id.return_value = None

        with pytest.raises(ServiceError, match="No chat history"):
            delete_chat_history(mock_client, "nb-123")

    def test_api_failure_raises_service_error(self, mock_client):
        mock_client.get_conversation_id.return_value = "conv-123"
        mock_client.delete_chat_history.side_effect = RuntimeError("server error")

        with pytest.raises(ServiceError, match="Failed to delete"):
            delete_chat_history(mock_client, "nb-123")

    def test_unacknowledged_deletion_raises_service_error(self, mock_client):
        mock_client.get_conversation_id.return_value = "conv-123"
        mock_client.delete_chat_history.return_value = False

        with pytest.raises(ServiceError, match="not acknowledged"):
            delete_chat_history(mock_client, "nb-123")


class TestQueryStart:
    """Test async query_start service function."""

    def test_returns_immediately_with_query_id(self, mock_client):
        # Make the mock query block for 2 seconds to prove we return immediately
        import time as _time

        def slow_query(**kwargs):
            _time.sleep(2)
            return {"answer": "done"}

        mock_client.query.side_effect = slow_query

        start = _time.monotonic()
        result = query_start(mock_client, "nb-123", "question")
        elapsed = _time.monotonic() - start

        assert elapsed < 1.0, "query_start should return immediately"
        assert "query_id" in result
        assert result["status"] == "in_progress"
        assert len(result["query_id"]) == 12

    def test_empty_query_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Query text is required"):
            query_start(mock_client, "nb-123", "")

    @patch("notebooklm_tools.services.chat.notebook_service")
    def test_empty_notebook_raises_validation_error(self, mock_notebook_service, mock_client):
        """Querying an empty notebook via async query_start should raise ValidationError."""
        mock_notebook_service.get_notebook.return_value = {"source_count": 0}
        with pytest.raises(ValidationError, match="Cannot query an empty notebook"):
            query_start(mock_client, "nb-123", "question")

    def test_whitespace_query_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="Query text is required"):
            query_start(mock_client, "nb-123", "   ")

    def test_multiple_starts_get_unique_ids(self, mock_client):
        mock_client.query.return_value = {"answer": "ok"}
        r1 = query_start(mock_client, "nb-123", "q1")
        r2 = query_start(mock_client, "nb-123", "q2")
        assert r1["query_id"] != r2["query_id"]

    def test_rejects_when_async_query_limit_is_full(self, mock_client, monkeypatch):
        import threading

        gate = threading.Event()

        def blocked_query(**kwargs):
            gate.wait(2)
            return {"answer": "done"}

        monkeypatch.setenv("NOTEBOOKLM_ASYNC_QUERY_MAX_INFLIGHT", "1")
        with _pending_lock:
            _pending_queries.clear()
        mock_client.query.side_effect = blocked_query

        first = query_start(mock_client, "nb-123", "q1", source_ids=["src-1"])
        try:
            with pytest.raises(ServiceError) as exc_info:
                query_start(mock_client, "nb-123", "q2", source_ids=["src-1"])
            assert exc_info.value.category == "resource_exhausted"
            assert exc_info.value.retryable is True
            assert exc_info.value.suggested_action == "poll_existing_queries"
        finally:
            gate.set()

        assert first["status"] == "in_progress"

    def test_thread_start_failure_releases_async_query_slot(self, mock_client, monkeypatch):
        import threading

        monkeypatch.setenv("NOTEBOOKLM_ASYNC_QUERY_MAX_INFLIGHT", "1")
        with _pending_lock:
            _pending_queries.clear()

        def cannot_start(self):
            raise RuntimeError("can't start new thread")

        monkeypatch.setattr(threading.Thread, "start", cannot_start)
        with pytest.raises(RuntimeError):
            query_start(mock_client, "nb-123", "q1", source_ids=["src-1"])

        with _pending_lock:
            assert not _pending_queries

    def test_completed_query_releases_async_query_slot(self, mock_client, monkeypatch):
        import time as _time

        monkeypatch.setenv("NOTEBOOKLM_ASYNC_QUERY_MAX_INFLIGHT", "1")
        with _pending_lock:
            _pending_queries.clear()
        mock_client.query.return_value = {"answer": "done"}

        first = query_start(mock_client, "nb-123", "q1", source_ids=["src-1"])
        for _ in range(100):
            if query_status(first["query_id"])["status"] == "completed":
                break
            _time.sleep(0.01)
        else:
            raise AssertionError("First async query did not complete")

        second = query_start(mock_client, "nb-123", "q2", source_ids=["src-1"])
        assert second["status"] == "in_progress"

    def test_ttl_cleanup_evicts_expired(self, mock_client):
        """Verify stale entries get cleaned up on the next query_start call."""
        import time as _time

        from notebooklm_tools.services.chat import (
            _pending_lock,
            _pending_queries,
        )

        mock_client.query.return_value = {"answer": "ok"}

        # Manually inject an expired entry
        with _pending_lock:
            _pending_queries["expired-id"] = {
                "status": "in_progress",
                "result": None,
                "error": None,
                "created_at": _time.monotonic() - 9999,
            }

        # Starting a new query should trigger cleanup
        query_start(mock_client, "nb-123", "question")

        with _pending_lock:
            assert "expired-id" not in _pending_queries


class TestQueryStatus:
    """Test async query_status service function."""

    def test_completed_query_returns_result(self, mock_client):
        import time as _time

        mock_client.query.return_value = {
            "answer": "The answer is 42.",
            "conversation_id": "conv-1",
            "sources_used": [],
            "citations": {},
            "references": [],
        }

        result = query_start(mock_client, "nb-123", "question")
        query_id = result["query_id"]

        # Wait for background thread to finish
        _time.sleep(1)

        status = query_status(query_id)
        assert status["status"] == "completed"
        assert status["result"]["answer"] == "The answer is 42."

    def test_in_progress_query(self, mock_client):
        import time as _time

        def slow_query(**kwargs):
            _time.sleep(5)
            return {"answer": "done"}

        mock_client.query.side_effect = slow_query

        result = query_start(mock_client, "nb-123", "question")
        query_id = result["query_id"]

        # Check immediately - should still be in progress
        status = query_status(query_id)
        assert status["status"] == "in_progress"
        assert status["result"] is None

    def test_error_query_returns_error_message(self, mock_client):
        import time as _time

        mock_client.query.side_effect = RuntimeError("API exploded")

        result = query_start(mock_client, "nb-123", "question")
        query_id = result["query_id"]

        # Wait for background thread to fail
        _time.sleep(1)

        status = query_status(query_id)
        assert status["status"] == "error"
        assert "API exploded" in status["error"]

    def test_unknown_query_id_raises_validation_error(self, mock_client):
        with pytest.raises(ValidationError, match="not found"):
            query_status("nonexistent-id")

    def test_completed_query_can_be_read_multiple_times_until_ttl(self, mock_client):
        import time as _time

        mock_client.query.return_value = {"answer": "ok"}

        result = query_start(mock_client, "nb-123", "question")
        query_id = result["query_id"]

        _time.sleep(1)

        first_status = query_status(query_id)
        second_status = query_status(query_id)

        assert first_status["status"] == "completed"
        assert second_status == first_status

    def test_in_progress_query_is_not_evicted_by_result_ttl(self, mock_client, monkeypatch):
        import time as _time

        monkeypatch.setenv("NOTEBOOKLM_ASYNC_QUERY_MAX_INFLIGHT", "1")
        with _pending_lock:
            _pending_queries.clear()
            _pending_queries["long-running"] = {
                "status": "in_progress",
                "result": None,
                "error": None,
                "error_details": None,
                "created_at": _time.monotonic() - _QUERY_TTL_SECONDS - 1,
                "expires_at": _time.monotonic() + 60,
                "finished_at": None,
            }

        with pytest.raises(ServiceError) as exc_info:
            query_start(mock_client, "nb-123", "blocked", source_ids=["src-1"])

        assert exc_info.value.category == "resource_exhausted"
        assert query_status("long-running")["status"] == "in_progress"

    def test_status_evicts_expired_query_before_reading(self, mock_client):
        import time as _time

        with _pending_lock:
            _pending_queries["expired-status-id"] = {
                "status": "completed",
                "result": {"answer": "expired"},
                "error": None,
                "error_details": None,
                "created_at": _time.monotonic() - (_QUERY_TTL_SECONDS * 2),
                "finished_at": _time.monotonic() - _QUERY_TTL_SECONDS - 1,
            }

        with pytest.raises(ValidationError, match="not found"):
            query_status("expired-status-id")

    def test_error_query_preserves_structured_error_details(self, mock_client):
        import time as _time

        mock_client.query.side_effect = QueryRejectedError(3)
        result = query_start(
            mock_client,
            "nb-123",
            "question",
            source_ids=["missing-source"],
        )

        for _ in range(100):
            status = query_status(result["query_id"])
            if status["status"] == "error":
                break
            _time.sleep(0.01)
        else:
            raise AssertionError("Background query did not reach an error state")

        assert status["status"] == "error"
        assert status["error_details"] == {
            "category": "invalid_argument",
            "provider_code": 3,
            "retryable": False,
            "suggested_action": "check_query_arguments",
            "debug_code": "query_invalid_argument",
        }

    def test_timeout_query_preserves_structured_error_details(self, mock_client):
        import time as _time

        mock_client.query.side_effect = httpx.ReadTimeout("The read operation timed out")
        result = query_start(
            mock_client,
            "nb-123",
            "question",
            source_ids=["src-1"],
            timeout=45.0,
        )

        for _ in range(100):
            status = query_status(result["query_id"])
            if status["status"] == "error":
                break
            _time.sleep(0.01)
        else:
            raise AssertionError("Background query did not reach an error state")

        assert status["error"] == (
            "NotebookLM did not respond within the configured query timeout."
        )
        assert status["error_details"] == {
            "category": "deadline_exceeded",
            "retryable": True,
            "suggested_action": "retry_with_longer_timeout",
            "debug_code": "query_deadline_exceeded",
        }
