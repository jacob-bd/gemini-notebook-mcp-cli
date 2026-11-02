"""Cross-notebook query service — query multiple notebooks and aggregate results."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from ..core.client import NotebookLMClient
from . import chat as chat_service
from . import notebooks as notebooks_service
from . import smart_select as smart_select_service
from ._compat import TypedDict
from .errors import ValidationError


class NotebookQueryResult(TypedDict):
    """Result from a single notebook query."""

    notebook_id: str
    notebook_title: str
    answer: str
    sources_used: list
    citations: dict
    references: list
    conversation_id: str | None
    error: str | None


class CrossNotebookResult(TypedDict):
    """Aggregated result from cross-notebook query."""

    query: str
    results: list[NotebookQueryResult]
    notebooks_queried: int
    notebooks_succeeded: int
    notebooks_failed: int


def _query_single_notebook(
    client: NotebookLMClient,
    notebook_id: str,
    notebook_title: str,
    query_text: str,
    timeout: float | None = None,
) -> NotebookQueryResult:
    """Query a single notebook, catching errors gracefully."""
    try:
        result = chat_service.query(
            client=client,
            notebook_id=notebook_id,
            query_text=query_text,
            timeout=timeout,
        )
        return {
            "notebook_id": notebook_id,
            "notebook_title": notebook_title,
            "answer": result["answer"],
            "sources_used": result["sources_used"],
            "citations": result.get("citations", {}),
            "references": result.get("references", []),
            "conversation_id": result.get("conversation_id"),
            "error": None,
        }
    except Exception as e:
        return {
            "notebook_id": notebook_id,
            "notebook_title": notebook_title,
            "answer": "",
            "sources_used": [],
            "citations": {},
            "references": [],
            "conversation_id": None,
            "error": str(e),
        }


def _resolve_notebook_ids(
    client: NotebookLMClient,
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    all_notebooks: bool = False,
) -> list[tuple[str, str]]:
    """Resolve notebook selection to list of (id, title) tuples.

    Args:
        client: Authenticated client
        notebook_names: Explicit notebook names/IDs
        tags: Select by tags via smart_select
        all_notebooks: Query all notebooks

    Returns:
        List of (notebook_id, title) tuples

    Raises:
        ValidationError: If no selection method specified
        ServiceError: If resolution fails
    """
    if not notebook_names and not tags and not all_notebooks:
        raise ValidationError(
            "Must specify notebooks, tags, or --all.",
            user_message="Please specify --notebooks, --tags, or --all.",
        )

    if all_notebooks:
        result = notebooks_service.list_notebooks(client)
        return [(nb["id"], nb["title"]) for nb in result["notebooks"]]

    if tags:
        tag_query = " ".join(tags)
        select_result = smart_select_service.smart_select(tag_query)
        if not select_result["matched_notebooks"]:
            raise ValidationError(
                f"No notebooks matched tags: {tags}",
                user_message=f"No notebooks found with tags: {', '.join(tags)}",
            )
        return [
            (entry["notebook_id"], entry.get("notebook_title", ""))
            for entry in select_result["matched_notebooks"]
        ]

    if notebook_names:
        # Try to match by title first, then treat as IDs
        all_nbs = notebooks_service.list_notebooks(client)
        title_map = {nb["title"].lower(): (nb["id"], nb["title"]) for nb in all_nbs["notebooks"]}

        resolved = []
        for name in notebook_names:
            name_lower = name.strip().lower()
            if name_lower in title_map:
                resolved.append(title_map[name_lower])
            else:
                # Assume it's an ID
                resolved.append((name.strip(), name.strip()))
        return resolved

    return []


def cross_notebook_query(
    client: NotebookLMClient,
    query_text: str,
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    all_notebooks: bool = False,
    max_concurrent: int = 5,
    timeout: float | None = None,
) -> CrossNotebookResult:
    """Query multiple notebooks and aggregate results.

    Args:
        client: Authenticated NotebookLM client
        query_text: Question to ask across notebooks
        notebook_names: Specific notebook names or IDs
        tags: Select notebooks by tags
        all_notebooks: Query all notebooks
        max_concurrent: Max parallel queries (default 5, respects rate limits)
        timeout: Per-query timeout in seconds

    Returns:
        CrossNotebookResult with per-notebook answers

    Raises:
        ValidationError: If query or selection is invalid
        ServiceError: If resolution fails
    """
    if not query_text or not query_text.strip():
        raise ValidationError(
            "Query text is required.",
            user_message="Please provide a question to ask.",
        )

    notebooks = _resolve_notebook_ids(client, notebook_names, tags, all_notebooks)

    if not notebooks:
        return {
            "query": query_text,
            "results": [],
            "notebooks_queried": 0,
            "notebooks_succeeded": 0,
            "notebooks_failed": 0,
        }

    results: list[NotebookQueryResult] = []

    with ThreadPoolExecutor(max_workers=min(max_concurrent, len(notebooks))) as executor:
        futures = {
            executor.submit(_query_single_notebook, client, nb_id, nb_title, query_text, timeout): (
                nb_id,
                nb_title,
            )
            for nb_id, nb_title in notebooks
        }

        for future in as_completed(futures):
            results.append(future.result())

    # Sort results: successful first, then by notebook title
    results.sort(key=lambda r: (r["error"] is not None, r["notebook_title"]))

    succeeded = sum(1 for r in results if r["error"] is None)

    return {
        "query": query_text,
        "results": results,
        "notebooks_queried": len(notebooks),
        "notebooks_succeeded": succeeded,
        "notebooks_failed": len(notebooks) - succeeded,
    }
