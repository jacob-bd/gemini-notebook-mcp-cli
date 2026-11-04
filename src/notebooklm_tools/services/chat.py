"""Chat service — shared business logic for notebook querying and chat configuration."""

import logging
import os
import threading
import time
import uuid
from typing import Any

import httpx

from ..core.client import NotebookLMClient
from ..core.conversation import DEFAULT_QUERY_TIMEOUT, QueryRejectedError
from . import notebooks as notebook_service
from ._compat import TypedDict
from .errors import ServiceError, ValidationError

logger = logging.getLogger(__name__)

VALID_GOALS = ("default", "learning_guide", "custom")
VALID_RESPONSE_LENGTHS = ("default", "longer", "shorter")
MAX_PROMPT_LENGTH = 10_000


class _QueryBudget:
    """Track the wall-clock budget for one query operation."""

    def __init__(self, timeout: float | None):
        effective_timeout = DEFAULT_QUERY_TIMEOUT if timeout is None else timeout
        self._deadline = time.monotonic() + effective_timeout

    def remaining(self) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise httpx.ReadTimeout("The query deadline expired before the next request")
        return remaining


_QUERY_REJECTION_METADATA: dict[int, dict[str, str | bool]] = {
    1: {"category": "cancelled", "retryable": False, "suggested_action": "submit_again_if_needed"},
    3: {
        "category": "invalid_argument",
        "retryable": False,
        "suggested_action": "check_query_arguments",
    },
    4: {
        "category": "deadline_exceeded",
        "retryable": True,
        "suggested_action": "retry_with_longer_timeout",
    },
    5: {
        "category": "not_found",
        "retryable": False,
        "suggested_action": "check_notebook_and_source_ids",
    },
    7: {
        "category": "permission_denied",
        "retryable": False,
        "suggested_action": "check_access_permissions",
    },
    8: {
        "category": "resource_exhausted",
        "retryable": True,
        "suggested_action": "retry_after_delay",
    },
    13: {"category": "internal", "retryable": True, "suggested_action": "retry_after_delay"},
    14: {"category": "unavailable", "retryable": True, "suggested_action": "retry_after_delay"},
    16: {"category": "unauthenticated", "retryable": False, "suggested_action": "run_nlm_login"},
}


def _query_rejected_service_error(error: QueryRejectedError) -> ServiceError:
    """Map a provider query rejection to actionable, structured metadata."""
    metadata = _QUERY_REJECTION_METADATA.get(
        error.error_code,
        {
            "category": "provider_error",
            "retryable": False,
            "suggested_action": "inspect_provider_error",
        },
    )
    category = str(metadata["category"])
    messages = {
        3: "The query request is invalid. Check the notebook ID, source IDs, and query arguments.",
        5: "The requested notebook or source was not found. Check the supplied IDs.",
        7: "Access to the requested notebook or source was denied.",
        8: "NotebookLM temporarily rejected the query because a usage limit was reached.",
        16: "NotebookLM authentication is no longer valid. Run 'nlm login' and retry.",
    }
    hints = {
        3: "Correct the invalid notebook ID, source ID, or query argument before retrying.",
        5: "Verify that the notebook and selected sources still exist and belong to this account.",
        7: "Confirm that the active account has access to the notebook and selected sources.",
        8: "Wait before retrying the query.",
        16: "Run 'nlm login' for the active profile.",
    }
    return ServiceError(
        f"Query failed: {error}",
        user_message=messages.get(error.error_code, str(error)),
        hint=hints.get(error.error_code),
        debug_code=f"query_{category}",
        category=category,
        provider_code=error.error_code,
        retryable=bool(metadata["retryable"]),
        suggested_action=str(metadata["suggested_action"]),
    )


def _query_timeout_service_error(error: Exception) -> ServiceError:
    """Map transport timeouts to actionable query metadata."""
    return ServiceError(
        f"Query timed out: {error}",
        user_message="NotebookLM did not respond within the configured query timeout.",
        hint="Retry with a longer timeout, such as 180 seconds.",
        debug_code="query_deadline_exceeded",
        category="deadline_exceeded",
        retryable=True,
        suggested_action="retry_with_longer_timeout",
    )


def _resolve_query_source_ids(
    client: NotebookLMClient,
    notebook_id: str,
    source_ids: list[str] | None,
    budget: _QueryBudget,
) -> list[str] | None:
    """Validate a whole-notebook query and reuse its source IDs."""
    if source_ids:
        return source_ids

    try:
        is_enterprise = getattr(client, "_is_enterprise", None)
        if callable(is_enterprise) and is_enterprise():
            notebooks = client.list_notebooks()
            notebook = next((nb for nb in notebooks if nb.id == notebook_id), None)
            if notebook is None:
                raise ValidationError(
                    f"Notebook {notebook_id} not found.",
                    user_message=f"Notebook {notebook_id} not found.",
                )
            if notebook.source_count == 0:
                raise ValidationError(
                    "Cannot query an empty notebook.",
                    user_message="This notebook has no sources to query. Add a source first using 'nlm source add' or 'nlm research start'.",
                )
            resolved_source_ids = [
                source["id"]
                for source in notebook.sources
                if isinstance(source, dict) and source.get("id")
            ]
        else:
            notebook = notebook_service.get_notebook(
                client,
                notebook_id,
                timeout=budget.remaining(),
            )
            if notebook["source_count"] == 0:
                raise ValidationError(
                    "Cannot query an empty notebook.",
                    user_message="This notebook has no sources to query. Add a source first using 'nlm source add' or 'nlm research start'.",
                )

            resolved_source_ids = [
                source["id"]
                for source in notebook.get("sources", [])
                if isinstance(source, dict) and source.get("id")
            ]
        return resolved_source_ids or None
    except ValidationError:
        raise
    except httpx.TimeoutException:
        raise
    except Exception:
        # Preserve the existing fallback: let the core client try to resolve
        # sources when the optional validation lookup fails.
        return source_ids


class QueryResult(TypedDict):
    """Result of a notebook query."""

    answer: str
    question: str
    conversation_id: str | None
    sources_used: list[Any]
    citations: dict[str, Any]
    references: list[dict[str, Any]]


class PendingQueryState(TypedDict):
    """Tracked state for an async query."""

    status: str
    result: QueryResult | None
    error: str | None
    error_details: dict[str, str | int | bool] | None
    created_at: float
    expires_at: float
    finished_at: float | None


# --- Async query state management ---
_QUERY_TTL_SECONDS = 600  # 10 minutes
_DEFAULT_MAX_INFLIGHT_QUERIES = 8
_pending_queries: dict[str, PendingQueryState] = {}
_pending_lock = threading.Lock()


def _max_inflight_queries() -> int:
    """Return the configured async-query admission limit."""
    raw = os.environ.get("NOTEBOOKLM_ASYNC_QUERY_MAX_INFLIGHT", "").strip()
    if not raw:
        return _DEFAULT_MAX_INFLIGHT_QUERIES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_INFLIGHT_QUERIES
    return max(1, value)


class ConfigureResult(TypedDict):
    """Result of configuring chat settings."""

    notebook_id: str
    goal: str
    response_length: str
    message: str


def query(
    client: NotebookLMClient,
    notebook_id: str,
    query_text: str,
    source_ids: list[str] | None = None,
    conversation_id: str | None = None,
    timeout: float | None = None,
    new_conversation: bool = False,
) -> QueryResult:
    """Query a notebook's sources with AI.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        query_text: Question to ask
        source_ids: Source IDs to query (default: all)
        conversation_id: For follow-up questions
        timeout: Wall-clock query budget in seconds (default: 120.0)
        new_conversation: Start a fresh conversation when conversation_id is omitted

    Returns:
        QueryResult with answer, conversation_id, and sources_used

    Raises:
        ValidationError: If query is empty
        ServiceError: If the query fails
    """
    if not query_text or not query_text.strip():
        raise ValidationError(
            "Query text is required.",
            user_message="Please provide a question to ask.",
        )

    budget = _QueryBudget(timeout)
    try:
        resolved_source_ids = _resolve_query_source_ids(
            client,
            notebook_id,
            source_ids,
            budget,
        )
        query_options = {}
        if new_conversation:
            query_options["new_conversation"] = True

        result = client.query(
            notebook_id=notebook_id,
            query_text=query_text,
            source_ids=resolved_source_ids,
            conversation_id=conversation_id,
            timeout=budget.remaining(),
            **query_options,
        )
    except QueryRejectedError as e:
        raise _query_rejected_service_error(e) from e
    except ValidationError:
        raise
    except httpx.TimeoutException as e:
        raise _query_timeout_service_error(e) from e
    except Exception as e:
        raise ServiceError(f"Query failed: {e}") from e

    if result:
        answer = result.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise ServiceError(
                "Query returned empty answer",
                user_message="The notebook returned no answer. Please retry the query.",
            )

        return {
            "answer": answer,
            "question": query_text,
            "conversation_id": result.get("conversation_id"),
            "sources_used": result.get("sources_used", []),
            "citations": result.get("citations", {}),
            "references": result.get("references", []),
        }

    raise ServiceError(
        "Query returned empty result",
        user_message="Failed to get a response from the notebook.",
    )


def configure_chat(
    client: NotebookLMClient,
    notebook_id: str,
    goal: str = "default",
    custom_prompt: str | None = None,
    response_length: str = "default",
) -> ConfigureResult:
    """Configure notebook chat settings.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        goal: default, learning_guide, or custom
        custom_prompt: Required when goal=custom (max 10000 chars)
        response_length: default, longer, or shorter

    Returns:
        ConfigureResult with updated settings

    Raises:
        ValidationError: If goal, response_length, or prompt is invalid
        ServiceError: If configuration fails
    """
    if goal not in VALID_GOALS:
        raise ValidationError(
            f"Invalid goal '{goal}'. Must be one of: {', '.join(VALID_GOALS)}",
        )

    if goal == "custom" and not custom_prompt:
        raise ValidationError(
            "Custom prompt is required when goal is 'custom'.",
            user_message="--prompt is required when goal is 'custom'.",
        )

    if custom_prompt and len(custom_prompt) > MAX_PROMPT_LENGTH:
        raise ValidationError(
            f"Custom prompt exceeds {MAX_PROMPT_LENGTH} character limit ({len(custom_prompt)} chars).",
            user_message=f"Custom prompt must be {MAX_PROMPT_LENGTH} characters or less.",
        )

    if response_length not in VALID_RESPONSE_LENGTHS:
        raise ValidationError(
            f"Invalid response_length '{response_length}'. Must be one of: {', '.join(VALID_RESPONSE_LENGTHS)}",
        )

    try:
        result = client.configure_chat(
            notebook_id=notebook_id,
            goal=goal,
            custom_prompt=custom_prompt,
            response_length=response_length,
        )
    except Exception as e:
        raise ServiceError(f"Failed to configure chat: {e}") from e

    if result:
        return {
            "notebook_id": notebook_id,
            "goal": goal,
            "response_length": response_length,
            "message": "Chat settings updated.",
        }

    raise ServiceError(
        "Chat configuration returned falsy result",
        user_message="Failed to configure chat — no confirmation from API.",
    )


class DeleteChatHistoryResult(TypedDict):
    """Result of deleting chat history."""

    notebook_id: str
    conversation_id: str
    message: str


def delete_chat_history(
    client: NotebookLMClient,
    notebook_id: str,
) -> DeleteChatHistoryResult:
    """Delete the chat history for a notebook.

    Fetches the notebook's persistent conversation ID, then deletes
    the associated chat history from the server.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID

    Returns:
        DeleteChatHistoryResult with confirmation message

    Raises:
        ServiceError: If no chat history exists or deletion fails
    """
    conv_id = client.get_conversation_id(notebook_id)
    if not conv_id:
        raise ServiceError(
            "No chat history found for this notebook.",
            user_message="This notebook has no chat history to delete.",
        )

    try:
        deleted = client.delete_chat_history(notebook_id, conv_id)
    except Exception as e:
        raise ServiceError(f"Failed to delete chat history: {e}") from e

    if not deleted:
        raise ServiceError(
            "Chat history deletion was not acknowledged by the server.",
            user_message="NotebookLM did not confirm that the chat history was deleted.",
        )

    return {
        "notebook_id": notebook_id,
        "conversation_id": conv_id,
        "message": "Chat history deleted.",
    }


# --- Async query polling ---


class QueryStartResult(TypedDict):
    """Result of starting an async query."""

    query_id: str
    status: str
    message: str


class QueryStatusResult(TypedDict):
    """Result of polling an async query."""

    query_id: str
    status: str
    result: QueryResult | None
    error: str | None
    error_details: dict[str, str | int | bool] | None


def _cleanup_expired_queries() -> None:
    """Evict stale running queries and finished results after their retention window."""
    now = time.monotonic()
    expired = []
    for qid, entry in _pending_queries.items():
        if entry["status"] == "in_progress":
            expires_at = entry.get("expires_at", entry["created_at"] + _QUERY_TTL_SECONDS)
            if now > expires_at:
                expired.append(qid)
            continue
        finished_at = entry.get("finished_at") or entry["created_at"]
        if now - finished_at > _QUERY_TTL_SECONDS:
            expired.append(qid)
    for qid in expired:
        logger.debug("Evicting expired async query %s", qid)
        del _pending_queries[qid]


def _run_query_in_background(
    query_id: str,
    client: NotebookLMClient,
    notebook_id: str,
    query_text: str,
    source_ids: list[str] | None,
    conversation_id: str | None,
    timeout: float | None,
    new_conversation: bool,
) -> None:
    """Background thread target that executes the query and stores the result."""
    try:
        result = query(
            client,
            notebook_id,
            query_text,
            source_ids=source_ids,
            conversation_id=conversation_id,
            timeout=timeout,
            new_conversation=new_conversation,
        )
        with _pending_lock:
            if query_id in _pending_queries:
                _pending_queries[query_id]["status"] = "completed"
                _pending_queries[query_id]["result"] = result
                _pending_queries[query_id]["finished_at"] = time.monotonic()
    except Exception as e:
        with _pending_lock:
            if query_id in _pending_queries:
                _pending_queries[query_id]["status"] = "error"
                _pending_queries[query_id]["finished_at"] = time.monotonic()
                if isinstance(e, ServiceError):
                    _pending_queries[query_id]["error"] = e.user_message
                    _pending_queries[query_id]["error_details"] = e.details() or None
                else:
                    _pending_queries[query_id]["error"] = str(e)


def query_start(
    client: NotebookLMClient,
    notebook_id: str,
    query_text: str,
    source_ids: list[str] | None = None,
    conversation_id: str | None = None,
    timeout: float | None = None,
    new_conversation: bool = False,
) -> QueryStartResult:
    """Start a notebook query in a background thread for async polling.

    Returns immediately with a query_id. Use query_status() to poll for the result.
    This avoids MCP client timeouts on large notebooks where Google's response
    takes longer than the client allows.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        query_text: Question to ask
        source_ids: Source IDs to query (default: all)
        conversation_id: For follow-up questions
        timeout: Wall-clock query budget in seconds (default: 120.0)
        new_conversation: Start a fresh conversation when conversation_id is omitted

    Returns:
        QueryStartResult with query_id and initial status

    Raises:
        ValidationError: If query text is empty
    """
    if not query_text or not query_text.strip():
        raise ValidationError(
            "Query text is required.",
            user_message="Please provide a question to ask.",
        )

    query_id = uuid.uuid4().hex[:12]
    created_at = time.monotonic()
    effective_timeout = DEFAULT_QUERY_TIMEOUT if timeout is None else max(0.0, timeout)
    expires_at = created_at + max(_QUERY_TTL_SECONDS, effective_timeout)

    with _pending_lock:
        _cleanup_expired_queries()
        inflight = sum(1 for entry in _pending_queries.values() if entry["status"] == "in_progress")
        limit = _max_inflight_queries()
        if inflight >= limit:
            raise ServiceError(
                f"Async query limit reached ({inflight}/{limit})",
                user_message=(
                    f"Too many async notebook queries are already running ({inflight}/{limit})."
                ),
                hint="Poll existing query IDs and retry after one finishes.",
                category="resource_exhausted",
                retryable=True,
                suggested_action="poll_existing_queries",
            )
        _pending_queries[query_id] = {
            "status": "in_progress",
            "result": None,
            "error": None,
            "error_details": None,
            "created_at": created_at,
            "expires_at": expires_at,
            "finished_at": None,
        }

    budget = _QueryBudget(timeout)
    try:
        resolved_source_ids = _resolve_query_source_ids(
            client,
            notebook_id,
            source_ids,
            budget,
        )
        worker_timeout = budget.remaining()
    except httpx.TimeoutException as e:
        with _pending_lock:
            _pending_queries.pop(query_id, None)
        raise _query_timeout_service_error(e) from e
    except Exception:
        with _pending_lock:
            _pending_queries.pop(query_id, None)
        raise

    thread = threading.Thread(
        target=_run_query_in_background,
        args=(
            query_id,
            client,
            notebook_id,
            query_text,
            resolved_source_ids,
            conversation_id,
            worker_timeout,
            new_conversation,
        ),
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _pending_lock:
            _pending_queries.pop(query_id, None)
        raise

    return {
        "query_id": query_id,
        "status": "in_progress",
        "message": "Query started. Use notebook_query_status to poll for the result.",
    }


def query_status(query_id: str) -> QueryStatusResult:
    """Check the status of an async query.

    Args:
        query_id: The query ID returned by query_start()

    Returns:
        QueryStatusResult with current status and result if completed

    Raises:
        ValidationError: If query_id is not found
    """
    with _pending_lock:
        _cleanup_expired_queries()
        entry = _pending_queries.get(query_id)
        if entry is None:
            raise ValidationError(
                f"Query ID '{query_id}' not found.",
                user_message=(
                    f"Query ID '{query_id}' not found. It may have expired "
                    f"(queries are kept for {_QUERY_TTL_SECONDS // 60} minutes) "
                    "or was never started."
                ),
            )

        result: QueryStatusResult = {
            "query_id": query_id,
            "status": entry["status"],
            "result": entry["result"],
            "error": entry["error"],
            "error_details": entry["error_details"],
        }

        return result
