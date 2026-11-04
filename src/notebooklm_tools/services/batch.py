"""Batch operations service — perform operations across multiple notebooks."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..core.client import NotebookLMClient
from . import chat as chat_service
from . import notebooks as notebooks_service
from . import sources as sources_service
from . import studio as studio_service
from ._compat import TypedDict
from .errors import ValidationError


class BatchItemResult(TypedDict):
    """Result for a single item in a batch operation."""

    notebook_id: str
    notebook_title: str
    success: bool
    result: Any
    error: str | None


class BatchResult(TypedDict):
    """Aggregated batch operation result."""

    operation: str
    items: list[BatchItemResult]
    total: int
    succeeded: int
    failed: int


def _resolve_targets(
    client: NotebookLMClient,
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    all_notebooks: bool = False,
) -> list[tuple[str, str]]:
    """Resolve batch targets to (id, title) tuples. Reuses cross_notebook logic."""
    from . import cross_notebook as cross_notebook_service

    return cross_notebook_service._resolve_notebook_ids(client, notebook_names, tags, all_notebooks)


def _run_batch(
    operation: str,
    targets: list[tuple[str, str]],
    fn,
    max_concurrent: int = 5,
) -> BatchResult:
    """Execute a function across multiple targets in parallel."""
    if not isinstance(max_concurrent, int) or not 1 <= max_concurrent <= 8:
        raise ValidationError(
            "max_concurrent must be between 1 and 8.",
            user_message="Concurrency must be between 1 and 8.",
        )
    results: list[BatchItemResult] = []

    with ThreadPoolExecutor(max_workers=min(max_concurrent, len(targets))) as executor:
        futures = {}
        for nb_id, nb_title in targets:
            future = executor.submit(fn, nb_id, nb_title)
            futures[future] = (nb_id, nb_title)

        for future in as_completed(futures):
            nb_id, nb_title = futures[future]
            try:
                result = future.result()
                results.append(
                    {
                        "notebook_id": nb_id,
                        "notebook_title": nb_title,
                        "success": True,
                        "result": result,
                        "error": None,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "notebook_id": nb_id,
                        "notebook_title": nb_title,
                        "success": False,
                        "result": None,
                        "error": str(e),
                    }
                )

    results.sort(key=lambda r: (not r["success"], r["notebook_title"]))
    succeeded = sum(1 for r in results if r["success"])

    return {
        "operation": operation,
        "items": results,
        "total": len(targets),
        "succeeded": succeeded,
        "failed": len(targets) - succeeded,
    }


def batch_query(
    client: NotebookLMClient,
    query_text: str,
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    all_notebooks: bool = False,
    max_concurrent: int = 5,
) -> BatchResult:
    """Query multiple notebooks with the same question.

    This is similar to cross_notebook_query but returns raw per-notebook results
    without aggregation.

    Args:
        client: Authenticated client
        query_text: Question to ask
        notebook_names: Specific notebook names or IDs
        tags: Select by tags
        all_notebooks: Query all
        max_concurrent: Max parallel queries
    """
    if not query_text or not query_text.strip():
        raise ValidationError("Query text is required.", user_message="Please provide a question.")

    targets = _resolve_targets(client, notebook_names, tags, all_notebooks)
    if not targets:
        return {"operation": "batch_query", "items": [], "total": 0, "succeeded": 0, "failed": 0}

    def query_fn(nb_id, nb_title):
        return chat_service.query(client, nb_id, query_text)

    return _run_batch("batch_query", targets, query_fn, max_concurrent)


def batch_add_source(
    client: NotebookLMClient,
    source_url: str,
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    all_notebooks: bool = False,
    max_concurrent: int = 3,
) -> BatchResult:
    """Add the same source URL to multiple notebooks.

    Args:
        client: Authenticated client
        source_url: URL to add as source
        notebook_names: Target notebooks
        tags: Select by tags
        all_notebooks: All notebooks
        max_concurrent: Max parallel ops (lower default for writes)
    """
    if not source_url or not source_url.strip():
        raise ValidationError("Source URL is required.", user_message="Please provide a URL.")

    targets = _resolve_targets(client, notebook_names, tags, all_notebooks)
    if not targets:
        return {
            "operation": "batch_add_source",
            "items": [],
            "total": 0,
            "succeeded": 0,
            "failed": 0,
        }

    def add_fn(nb_id, nb_title):
        return sources_service.add_source(client, nb_id, source_type="url", url=source_url)

    return _run_batch("batch_add_source", targets, add_fn, max_concurrent)


def batch_create(
    client: NotebookLMClient,
    titles: list[str],
) -> BatchResult:
    """Create multiple notebooks at once.

    Args:
        client: Authenticated client
        titles: List of notebook titles to create
    """
    if not titles:
        raise ValidationError(
            "At least one title is required.", user_message="Please provide notebook titles."
        )

    targets = [(f"new-{i}", title) for i, title in enumerate(titles)]

    def create_fn(nb_id, nb_title):
        return notebooks_service.create_notebook(client, nb_title)

    return _run_batch("batch_create", targets, create_fn, max_concurrent=3)


def batch_delete(
    client: NotebookLMClient,
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    confirm: bool = False,
    max_concurrent: int = 3,
) -> BatchResult:
    """Delete multiple notebooks.

    Args:
        client: Authenticated client
        notebook_names: Notebooks to delete
        tags: Select by tags
        confirm: Must be True (safety check)
        max_concurrent: Max parallel ops
    """
    if not confirm:
        raise ValidationError(
            "Batch delete requires confirm=True.",
            user_message="Batch delete is IRREVERSIBLE. Set confirm=True after user approval.",
        )

    targets = _resolve_targets(client, notebook_names, tags, all_notebooks=False)
    if not targets:
        return {"operation": "batch_delete", "items": [], "total": 0, "succeeded": 0, "failed": 0}

    def delete_fn(nb_id, nb_title):
        return notebooks_service.delete_notebook(client, nb_id)

    return _run_batch("batch_delete", targets, delete_fn, max_concurrent)


def batch_studio(
    client: NotebookLMClient,
    artifact_type: str = "audio",
    notebook_names: list[str] | None = None,
    tags: list[str] | None = None,
    all_notebooks: bool = False,
    max_concurrent: int = 2,
) -> BatchResult:
    """Generate studio artifacts across multiple notebooks.

    Args:
        client: Authenticated client
        artifact_type: Type of artifact (audio, video, report, etc.)
        notebook_names: Target notebooks
        tags: Select by tags
        all_notebooks: All notebooks
        max_concurrent: Max parallel (lower for heavy ops)
    """
    targets = _resolve_targets(client, notebook_names, tags, all_notebooks)
    if not targets:
        return {"operation": "batch_studio", "items": [], "total": 0, "succeeded": 0, "failed": 0}

    def studio_fn(nb_id, nb_title):
        return studio_service.create_artifact(client, nb_id, artifact_type)

    return _run_batch("batch_studio", targets, studio_fn, max_concurrent)
