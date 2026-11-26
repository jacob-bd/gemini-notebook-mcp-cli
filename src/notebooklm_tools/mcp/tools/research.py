"""Research tools - Deep research and source discovery."""

from ...services import ServiceError
from ...services import research as research_service
from ._utils import ResultDict, coerce_list, error_result, get_client, logged_tool


@logged_tool()
def research_start(
    query: str,
    source: str = "web",
    mode: str = "fast",
    notebook_id: str | None = None,
    title: str | None = None,
) -> ResultDict:
    """Deep research / fast research: Search web or Google Drive to FIND NEW sources.

    Use this for: "deep research on X", "find sources about Y", "search web for Z", "search Drive".
    Workflow: research_start -> poll research_status -> research_import.

    Args:
        query: What to search for (e.g. "quantum computing advances")
        source: web|drive (where to search)
        mode: fast (~30s, ~10 sources) | deep (~5min, ~40 sources, web only)
        notebook_id: Existing notebook (creates new if not provided)
        title: Title for new notebook
    """
    try:
        client = get_client()

        if not notebook_id and title:
            from ...services import notebooks as notebook_service

            nb_result = notebook_service.create_notebook(client, title=title)
            notebook_id = nb_result["notebook_id"]
        elif not notebook_id:
            return error_result(
                "Please provide either a notebook_id or a title for a new notebook."
            )

        result = research_service.start_research(
            client,
            notebook_id,
            query,
            source=source,
            mode=mode,
        )
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def research_status(
    notebook_id: str,
    poll_interval: int = 30,
    max_wait: int = 900,
    compact: bool = True,
    task_id: str | None = None,
    query: str | None = None,
    auto_import: bool = False,
) -> ResultDict:
    """Poll research progress. Blocks until complete or timeout.

    Args:
        notebook_id: Notebook UUID
        poll_interval: Seconds between polls (default: 30)
        max_wait: Max seconds to wait (default: 900, 0=single poll)
        compact: If True (default), truncate report and limit sources shown to save tokens.
                Use compact=False to get full details.
        task_id: Optional Task ID to poll for a specific research task.
        query: Optional query text for fallback matching when task_id changes (deep research).
            Contributed by @saitrogen (PR #15).
        auto_import: If True, require the original task_id from research_start and
            use a durable at-most-once claim. Uncertain mutations are never
            retried automatically; reconcile existing sources manually.
                    If False (default), returns next_action hint to call research_import manually.
    """
    try:
        client = get_client()
        result = research_service.poll_research(
            client,
            notebook_id,
            task_id=task_id,
            query=query,
            compact=compact,
            poll_interval=poll_interval,
            max_wait=max_wait,
            auto_import=auto_import,
        )
        return dict(result)
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def research_import(
    notebook_id: str,
    task_id: str,
    source_indices: str | list[int] | None = None,
    timeout: float = 300.0,
    cited_only: bool = False,
) -> ResultDict:
    """Import discovered sources into notebook.

    Call after research_status shows status="completed".

    Args:
        notebook_id: Notebook UUID
        task_id: Research task ID
        source_indices: Source indices to import (default: all)
        timeout: Import timeout in seconds (default: 300, increase for large notebooks)
        cited_only: Import only sources cited by the research report.
            Overrides source_indices when enabled.
    """
    try:
        client = get_client()
        # Coerce list params from MCP clients (may arrive as strings)
        source_indices = coerce_list(source_indices, item_type=int)
        result = research_service.import_research(
            client,
            notebook_id,
            task_id,
            source_indices=source_indices,
            timeout=timeout,
            cited_only=cited_only,
        )
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))
