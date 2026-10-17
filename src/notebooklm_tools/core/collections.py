"""CollectionsMixin - Native NotebookLM collections management operations."""

import logging
import time

from .base import BaseClient

logger = logging.getLogger(__name__)


class CollectionsMixin(BaseClient):
    """Mixin for native NotebookLM collections management operations."""

    def _get_collections_header(self) -> list:
        """Returns the standard header for collections RPC operations."""
        return [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]]

    def list_collections(self) -> list[dict]:
        """Lists all collections by temporarily creating a hidden one and deleting it.

        Returns:
            List of collections, where each collection is a dict with:
                - id: str
                - name: str
                - notebook_ids: list[str]
                - emoji: str
        """
        header = self._get_collections_header()
        temp_name = f"_temp_list_query_{int(time.time())}"

        # 1. Create a temporary collection to force Google to return the list
        params_create = [header, None, None, None, None, [[temp_name], None, []], 3]

        result = self._call_rpc("agX4Bc", params_create)

        collections = []
        temp_id = None

        if result and len(result) > 2 and isinstance(result[2], list):
            for col in result[2]:
                if not isinstance(col, list) or len(col) < 3:
                    continue

                col_name = col[0] or ""
                col_notebooks = col[1] or []
                col_id = col[2] or ""
                col_emoji = col[3] if len(col) > 3 else ""

                if col_name == temp_name:
                    temp_id = col_id
                    continue

                collections.append(
                    {
                        "id": col_id,
                        "name": col_name,
                        "notebook_ids": col_notebooks,
                        "emoji": col_emoji,
                    }
                )

        # 2. Delete the temporary collection in the background
        if temp_id:
            try:
                self.delete_collection(temp_id)
            except Exception as e:
                logger.warning(f"Failed to cleanup temporary listing collection {temp_id}: {e}")

        return collections

    def create_collection(self, name: str, notebook_ids: list[str] = None) -> dict:
        """Creates a new collection with the given name and notebooks.

        Args:
            name: Name of the collection
            notebook_ids: List of notebook UUIDs to include

        Returns:
            The created collection dict.
        """
        header = self._get_collections_header()
        notebooks = notebook_ids or []

        params = [header, None, None, None, None, [[name], None, notebooks], 3]

        result = self._call_rpc("agX4Bc", params)

        # Find the newly created collection in the returned list
        if result and len(result) > 2 and isinstance(result[2], list):
            for col in result[2]:
                if isinstance(col, list) and len(col) >= 3 and col[0] == name:
                    return {
                        "id": col[2],
                        "name": col[0],
                        "notebook_ids": col[1] or [],
                        "emoji": col[3] if len(col) > 3 else "",
                    }

        raise RuntimeError("Failed to confirm collection creation on Google backend")

    def edit_collection(
        self, collection_id: str, name: str = None, notebook_ids: list[str] = None
    ) -> bool:
        """Edits an existing collection's name and/or notebooks.

        Args:
            collection_id: UUID of the collection to edit
            name: New name (optional)
            notebook_ids: New complete list of notebook IDs (optional)

        The le8sX RPC takes one operation per call (captured from the web UI):
            rename:  [[[name]]]
            add:     [[None, None, None, [[id, ...]]], []]
            remove:  [[None, None, None, None, [[id, ...]]], []]
        Sending the whole list, or name and notebooks together, returns INVALID_ARGUMENT.

        Membership is read before anything is written, so an unknown collection
        fails without applying the rename. The operations are not atomic: a
        later step can fail after an earlier one succeeded.
        """
        header = self._get_collections_header()

        def _edit(payload) -> bool:
            result = self._call_rpc("le8sX", [header, None, collection_id, payload, 3])
            return result == [] or result is not None

        to_add = []
        to_remove = []
        if notebook_ids is not None:
            current = None
            for col in self.list_collections():
                if col["id"] == collection_id:
                    current = col["notebook_ids"]
                    break
            if current is None:
                raise ValueError(f"Collection not found: {collection_id}")
            wanted = list(dict.fromkeys(notebook_ids))
            to_add = [i for i in wanted if i not in current]
            to_remove = [i for i in current if i not in wanted]

        ok = True
        if name is not None:
            ok = _edit([[[name]]]) and ok
        if to_add:
            ok = _edit([[None, None, None, [to_add]], []]) and ok
        if to_remove:
            ok = _edit([[None, None, None, None, [to_remove]], []]) and ok

        return ok

    def set_collection_emoji(self, collection_id: str, emoji: str) -> bool:
        """Sets or clears the emoji marker on a collection (pass "" to clear)."""
        header = self._get_collections_header()
        params = [header, None, collection_id, [[[None, emoji]]], 3]
        result = self._call_rpc("le8sX", params)
        return result == [] or result is not None

    def delete_collection(self, collection_id: str) -> bool:
        """Permanently deletes a collection. Notebooks are not deleted."""
        header = self._get_collections_header()
        params = [header, None, [collection_id], 3]
        result = self._call_rpc("GyzE7e", params)
        return result == [] or result is not None
