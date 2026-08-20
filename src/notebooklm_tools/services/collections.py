"""Collections service — shared business logic for native collections CRUD and metadata operations."""

from ..core.client import NotebookLMClient
from .errors import ServiceError, ValidationError


def list_collections(client: NotebookLMClient) -> dict:
    """List all native collections."""
    try:
        collections = client.list_collections()
        return {"collections": collections, "count": len(collections)}
    except Exception as e:
        raise ServiceError(f"Failed to list collections: {e}") from e


def create_collection(client: NotebookLMClient, name: str, notebook_ids: list[str] = None) -> dict:
    """Create a new collection.

    Args:
        client: Authenticated NotebookLM client
        name: Name of the collection
        notebook_ids: Optional list of notebook UUIDs to include
    """
    if not name or not name.strip():
        raise ValidationError(
            "Collection name is required.",
            user_message="Collection name cannot be empty.",
        )

    try:
        col = client.create_collection(name, notebook_ids)
        return {
            "collection_id": col["id"],
            "collection": col,
            "message": f"Created collection: {name}",
        }
    except Exception as e:
        raise ServiceError(f"Failed to create collection: {e}") from e


def edit_collection(
    client: NotebookLMClient, collection_id: str, name: str = None, notebook_ids: list[str] = None
) -> dict:
    """Edit an existing collection.

    Args:
        client: Authenticated NotebookLM client
        collection_id: UUID of the collection
        name: New name (optional)
        notebook_ids: New complete list of notebook IDs (optional)
    """
    if name is not None and not name.strip():
        raise ValidationError(
            "New collection name cannot be empty.",
            user_message="Collection name cannot be empty.",
        )

    try:
        success = client.edit_collection(collection_id, name, notebook_ids)
        if success:
            return {
                "collection_id": collection_id,
                "message": f"Updated collection {collection_id}",
            }
        raise ServiceError("Google backend returned falsy result for collection edit")
    except Exception as e:
        raise ServiceError(f"Failed to edit collection: {e}") from e


def set_collection_emoji(client: NotebookLMClient, collection_id: str, emoji: str) -> dict:
    """Sets or clears the emoji marker on a collection.

    Args:
        client: Authenticated NotebookLM client
        collection_id: UUID of the collection
        emoji: Emoji character (use "" to clear)
    """
    try:
        success = client.set_collection_emoji(collection_id, emoji)
        if success:
            return {
                "collection_id": collection_id,
                "emoji": emoji,
                "message": f"Updated emoji to '{emoji}' for collection {collection_id}",
            }
        raise ServiceError("Google backend returned falsy result for collection emoji edit")
    except Exception as e:
        raise ServiceError(f"Failed to set collection emoji: {e}") from e


def delete_collection(client: NotebookLMClient, collection_id: str) -> dict:
    """Permanently delete a collection.

    Args:
        client: Authenticated NotebookLM client
        collection_id: UUID of the collection
    """
    try:
        success = client.delete_collection(collection_id)
        if success:
            return {"message": f"Collection {collection_id} has been permanently deleted."}
        raise ServiceError("Google backend returned falsy result for collection deletion")
    except Exception as e:
        raise ServiceError(f"Failed to delete collection: {e}") from e
