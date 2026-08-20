"""Collection tools - native NotebookLM collections management operations."""

from ...services import ServiceError
from ...services import collections as collections_service
from ._utils import ResultDict, error_result, get_client, logged_tool


@logged_tool()
def collection_list() -> ResultDict:
    """List all native collections."""
    try:
        client = get_client()
        result = collections_service.list_collections(client)
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def collection_create(name: str, notebook_ids: list[str] = None) -> ResultDict:
    """Create a new collection.

    Args:
        name: Name of the collection
        notebook_ids: List of notebook UUIDs to include in the collection (optional)
    """
    try:
        client = get_client()
        result = collections_service.create_collection(client, name, notebook_ids)
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def collection_edit(
    collection_id: str, name: str = None, notebook_ids: list[str] = None
) -> ResultDict:
    """Edit an existing collection's name and/or list of notebooks.

    Args:
        collection_id: UUID of the collection
        name: New name for the collection (optional)
        notebook_ids: New complete list of notebook UUIDs to include (optional)
    """
    try:
        client = get_client()
        result = collections_service.edit_collection(client, collection_id, name, notebook_ids)
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def collection_set_emoji(collection_id: str, emoji: str) -> ResultDict:
    """Set or clear the emoji marker on a collection.

    Args:
        collection_id: UUID of the collection
        emoji: Emoji character (use empty string "" to clear)
    """
    try:
        client = get_client()
        result = collections_service.set_collection_emoji(client, collection_id, emoji)
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))


@logged_tool()
def collection_delete(collection_id: str, confirm: bool = False) -> ResultDict:
    """Delete a collection permanently. Notebooks inside the collection are NOT deleted.

    Args:
        collection_id: UUID of the collection
        confirm: Must be True after user approval
    """
    if not confirm:
        return {
            "status": "error",
            "error": "Deletion not confirmed. You must ask the user to confirm "
            "before deleting. Set confirm=True only after user approval.",
            "warning": "This action is IRREVERSIBLE. The collection will be permanently deleted.",
        }

    try:
        client = get_client()
        result = collections_service.delete_collection(client, collection_id)
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))
