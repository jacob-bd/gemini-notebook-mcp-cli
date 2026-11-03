"""Target selection and concurrency must fail closed for batch operations."""

from unittest.mock import MagicMock, patch

import pytest

from notebooklm_tools.services.batch import _run_batch
from notebooklm_tools.services.cross_notebook import (
    _resolve_notebook_ids,
    cross_notebook_query,
)
from notebooklm_tools.services.errors import ValidationError


def test_duplicate_notebook_titles_require_explicit_id():
    notebooks = {
        "notebooks": [
            {"id": "nb-1", "title": "Case Notes"},
            {"id": "nb-2", "title": "case notes"},
        ]
    }
    with (
        patch(
            "notebooklm_tools.services.cross_notebook.notebooks_service.list_notebooks",
            return_value=notebooks,
        ),
        pytest.raises(ValidationError, match="Ambiguous notebook title"),
    ):
        _resolve_notebook_ids(MagicMock(), notebook_names=["Case Notes"])


def test_unique_name_resolution_deduplicates_repeated_target():
    notebooks = {"notebooks": [{"id": "nb-1", "title": "Case Notes"}]}
    with patch(
        "notebooklm_tools.services.cross_notebook.notebooks_service.list_notebooks",
        return_value=notebooks,
    ):
        result = _resolve_notebook_ids(MagicMock(), notebook_names=["Case Notes", "case notes"])
    assert result == [("nb-1", "Case Notes")]


@pytest.mark.parametrize("workers", [0, -1, 9, 10, 1.5])
def test_cross_notebook_rejects_invalid_worker_counts(workers):
    with pytest.raises(ValidationError, match="max_concurrent"):
        cross_notebook_query(MagicMock(), "Question", notebook_names=["id"], max_concurrent=workers)


@pytest.mark.parametrize("workers", [0, -1, 9, 50, 2.5])
def test_batch_rejects_invalid_worker_counts(workers):
    with pytest.raises(ValidationError, match="max_concurrent"):
        _run_batch("query", [("id", "Title")], lambda *_: None, max_concurrent=workers)
