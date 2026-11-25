"""Notebooks service — shared business logic for notebook CRUD and metadata operations."""

import httpx

from ..core.client import NotebookLMClient
from ..core.sources import source_url_from_metadata
from ..utils.config import get_notebook_url
from ._compat import TypedDict
from .errors import CreationError, NotFoundError, ServiceError, ValidationError


class NotebookInfo(TypedDict):
    """Notebook summary info."""

    id: str
    title: str
    source_count: int
    url: str
    ownership: str
    is_shared: bool
    created_at: str | None
    modified_at: str | None
    emoji: str | None


class NotebookListResult(TypedDict):
    """Result of listing notebooks."""

    notebooks: list[NotebookInfo]
    count: int
    owned_count: int
    shared_count: int
    shared_by_me_count: int


class SourceInfo(TypedDict):
    """Source summary in notebook details, with original URL when available."""

    id: str
    title: str
    url: str | None


class NotebookDetailResult(TypedDict):
    """Result of getting a single notebook's details."""

    notebook_id: str
    title: str
    source_count: int
    url: str
    sources: list[SourceInfo]
    emoji: str | None


class NotebookSummaryResult(TypedDict):
    """Result of AI-generated notebook summary."""

    summary: str
    suggested_topics: list[str]


class NotebookCreateResult(TypedDict):
    """Result of creating a notebook."""

    notebook_id: str
    title: str
    url: str
    message: str


class NotebookRenameResult(TypedDict):
    """Result of renaming a notebook."""

    notebook_id: str
    new_title: str
    message: str


class NotebookDeleteResult(TypedDict):
    """Result of deleting a notebook."""

    message: str


def notebook_url(client: NotebookLMClient, notebook_id: str) -> str:
    """Build a notebook link for the host used by this authenticated client."""
    profile_host = getattr(client, "_base_host", None)
    return get_notebook_url(
        notebook_id,
        profile_host=profile_host if isinstance(profile_host, str) else None,
    )


def list_notebooks(
    client: NotebookLMClient,
    max_results: int = 100,
) -> NotebookListResult:
    """List all notebooks.

    Args:
        client: Authenticated NotebookLM client
        max_results: Maximum notebooks to return

    Returns:
        NotebookListResult with notebooks and counts

    Raises:
        ServiceError: If listing fails
    """
    try:
        notebooks = client.list_notebooks()
    except Exception as e:
        raise ServiceError(f"Failed to list notebooks: {e}") from e

    owned_count = sum(1 for nb in notebooks if nb.is_owned)
    shared_count = len(notebooks) - owned_count
    shared_by_me_count = sum(1 for nb in notebooks if nb.is_owned and nb.is_shared)

    return {
        "notebooks": [
            {
                "id": nb.id,
                "title": nb.title,
                "source_count": nb.source_count,
                "url": notebook_url(client, nb.id),
                "ownership": nb.ownership,
                "is_shared": nb.is_shared,
                "created_at": nb.created_at,
                "modified_at": nb.modified_at,
                "emoji": getattr(nb, "emoji", None),
            }
            for nb in notebooks[:max_results]
        ],
        "count": len(notebooks),
        "owned_count": owned_count,
        "shared_count": shared_count,
        "shared_by_me_count": shared_by_me_count,
    }


def get_notebook(
    client: NotebookLMClient,
    notebook_id: str,
    timeout: float | None = None,
) -> NotebookDetailResult:
    """Get notebook details including source list.

    Handles raw RPC list responses from the API, normalising them into a
    clean typed dict.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID

    Returns:
        NotebookDetailResult with title, sources, etc.

    Raises:
        NotFoundError: If notebook not found
        ServiceError: If the API call fails
    """
    try:
        kwargs = {"timeout": timeout} if timeout is not None else {}
        nb = client.get_notebook(notebook_id, **kwargs)
    except httpx.TimeoutException:
        raise
    except Exception as e:
        raise ServiceError(f"Failed to get notebook: {e}") from e

    if not nb:
        raise NotFoundError(
            f"Notebook {notebook_id} not found",
            user_message=f"Notebook {notebook_id} not found.",
        )

    # The client may return raw RPC data (nested list) instead of a Notebook object.
    # Normalise that into a consistent result.
    if isinstance(nb, list):
        data = nb[0] if nb and isinstance(nb[0], list) else nb
        if isinstance(data, list) and len(data) >= 3:
            title = data[0] if isinstance(data[0], str) else "Untitled"
            sources_data = data[1] if len(data) > 1 and isinstance(data[1], list) else []
            nb_id = data[2] if len(data) > 2 else notebook_id
            emoji = data[3] if len(data) > 3 and isinstance(data[3], str) else None

            sources: list[SourceInfo] = []
            for src in sources_data:
                if isinstance(src, list) and len(src) >= 2:
                    src_id = src[0][0] if isinstance(src[0], list) and src[0] else src[0]
                    src_title = src[1] if len(src) > 1 else "Untitled"
                    metadata = src[2] if len(src) > 2 and isinstance(src[2], list) else []
                    source_type = metadata[4] if len(metadata) > 4 else None
                    sources.append(
                        {
                            "id": src_id,
                            "title": src_title,
                            "url": source_url_from_metadata(source_type, metadata),
                        }
                    )

            return {
                "notebook_id": nb_id,
                "title": title,
                "source_count": len(sources),
                "url": notebook_url(client, nb_id),
                "sources": sources,
                "emoji": emoji,
            }

    # Fallback: if nb is a dataclass-like object with attrs (e.g. from list_notebooks)
    if hasattr(nb, "id"):
        return {
            "notebook_id": nb.id,
            "title": getattr(nb, "title", "Untitled"),
            "source_count": getattr(nb, "source_count", 0),
            "url": notebook_url(client, nb.id),
            "sources": [],
            "emoji": getattr(nb, "emoji", None),
        }

    # Last-resort fallback
    raise ServiceError(
        f"Unexpected notebook data format: {str(nb)[:200]}",
        user_message="Received unexpected data format from the API.",
    )


def describe_notebook(
    client: NotebookLMClient,
    notebook_id: str,
) -> NotebookSummaryResult:
    """Get AI-generated notebook summary with suggested topics.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID

    Returns:
        NotebookSummaryResult with summary and topics

    Raises:
        ServiceError: If the summary call fails
    """
    try:
        result = client.get_notebook_summary(notebook_id)
    except Exception as e:
        raise ServiceError(f"Failed to get notebook summary: {e}") from e

    if result:
        return {
            "summary": result.get("summary", ""),
            "suggested_topics": result.get("suggested_topics", []),
        }

    raise ServiceError(
        "Notebook summary returned no data",
        user_message="Failed to get notebook summary — no data returned.",
    )


def create_notebook(
    client: NotebookLMClient,
    title: str = "",
) -> NotebookCreateResult:
    """Create a new notebook.

    Args:
        client: Authenticated NotebookLM client
        title: Notebook title (optional)

    Returns:
        NotebookCreateResult with notebook ID and URL

    Raises:
        CreationError: If creation fails
    """
    try:
        nb = client.create_notebook(title)
    except Exception as e:
        raise CreationError(f"Failed to create notebook: {e}") from e

    if nb and hasattr(nb, "id"):
        return {
            "notebook_id": nb.id,
            "title": nb.title,
            "url": notebook_url(client, nb.id),
            "message": f"Created notebook: {nb.title}",
        }

    raise CreationError(
        "Notebook creation returned no data",
        user_message="Failed to create notebook — no confirmation from API.",
    )


def rename_notebook(
    client: NotebookLMClient,
    notebook_id: str,
    new_title: str,
) -> NotebookRenameResult:
    """Rename a notebook.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        new_title: New title

    Returns:
        NotebookRenameResult

    Raises:
        ValidationError: If title is empty
        ServiceError: If rename fails
    """
    if not new_title or not new_title.strip():
        raise ValidationError(
            "New title is required.",
            user_message="Notebook title cannot be empty.",
        )

    try:
        result = client.rename_notebook(notebook_id, new_title)
    except Exception as e:
        raise ServiceError(f"Failed to rename notebook: {e}") from e

    if result:
        return {
            "notebook_id": notebook_id,
            "new_title": new_title,
            "message": f"Renamed notebook to: {new_title}",
        }

    raise ServiceError(
        "Rename returned falsy result",
        user_message="Rename may have failed — no confirmation from API.",
    )


def delete_notebook(
    client: NotebookLMClient,
    notebook_id: str,
) -> NotebookDeleteResult:
    """Delete a notebook permanently.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID

    Returns:
        NotebookDeleteResult

    Raises:
        ServiceError: If deletion fails
    """
    try:
        result = client.delete_notebook(notebook_id)
    except Exception as e:
        raise ServiceError(f"Failed to delete notebook: {e}") from e

    if result:
        return {
            "message": f"Notebook {notebook_id} has been permanently deleted.",
        }

    raise ServiceError(
        "Notebook deletion returned falsy result",
        user_message="Failed to delete notebook — no confirmation from API.",
    )
