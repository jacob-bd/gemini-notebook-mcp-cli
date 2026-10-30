"""Regression tests for evidence preserved in cross-notebook query results."""

from unittest.mock import MagicMock, patch

from notebooklm_tools.services.cross_notebook import (
    _query_single_notebook,
    cross_notebook_query,
)


def test_single_notebook_preserves_citations_references_and_conversation_id():
    evidence = {"source_id": "paper-1", "citation_number": 1, "cited_text": "Quoted evidence."}
    response = {
        "answer": "A cited finding [1]",
        "sources_used": ["paper-1"],
        "citations": {1: "paper-1"},
        "references": [evidence],
        "conversation_id": "conversation-1",
    }
    with patch("notebooklm_tools.services.cross_notebook.chat_service.query", return_value=response):
        result = _query_single_notebook(MagicMock(), "notebook-1", "Notebook 1", "Question")

    assert result["citations"] == {1: "paper-1"}
    assert result["references"] == [evidence]
    assert result["conversation_id"] == "conversation-1"
    assert result["error"] is None


def test_single_notebook_defaults_for_missing_optional_fields():
    response = {"answer": "Answer", "sources_used": []}
    with patch("notebooklm_tools.services.cross_notebook.chat_service.query", return_value=response):
        result = _query_single_notebook(MagicMock(), "notebook-1", "Notebook 1", "Question")

    assert result["citations"] == {}
    assert result["references"] == []
    assert result["conversation_id"] is None


def test_failed_query_returns_empty_evidence_without_leaking_other_sources():
    with patch("notebooklm_tools.services.cross_notebook.chat_service.query", side_effect=RuntimeError("rate limited")):
        result = _query_single_notebook(MagicMock(), "notebook-1", "Notebook 1", "Question")

    assert result["answer"] == ""
    assert result["sources_used"] == []
    assert result["citations"] == {}
    assert result["references"] == []
    assert result["conversation_id"] is None
    assert result["error"] == "rate limited"


def test_cross_notebook_keeps_each_notebooks_citations_separate():
    def answer_for_notebook(*, notebook_id, **kwargs):
        source_id = f"source-{notebook_id}"
        return {
            "answer": f"Finding from {notebook_id} [1]",
            "sources_used": [source_id],
            "citations": {1: source_id},
            "references": [{"source_id": source_id, "citation_number": 1, "cited_text": notebook_id}],
            "conversation_id": f"conversation-{notebook_id}",
        }

    with (
        patch("notebooklm_tools.services.cross_notebook._resolve_notebook_ids", return_value=[
            ("nb-a", "Notebook A"), ("nb-b", "Notebook B")
        ]),
        patch("notebooklm_tools.services.cross_notebook.chat_service.query", side_effect=answer_for_notebook),
    ):
        result = cross_notebook_query(MagicMock(), "Compare results", all_notebooks=True)

    assert result["notebooks_succeeded"] == 2
    assert result["notebooks_failed"] == 0
    results = {item["notebook_id"]: item for item in result["results"]}
    for nb_id in ("nb-a", "nb-b"):
        item = results[nb_id]
        assert item["citations"] == {1: f"source-{nb_id}"}
        assert item["references"][0]["cited_text"] == nb_id
        assert item["conversation_id"] == f"conversation-{nb_id}"


def test_cross_notebook_partial_failure_keeps_successful_evidence():
    def answer_or_fail(*, notebook_id, **kwargs):
        if notebook_id == "nb-b":
            raise RuntimeError("quota exceeded")
        return {
            "answer": "Supported [1]",
            "sources_used": ["paper-a"],
            "citations": {1: "paper-a"},
            "references": [{"source_id": "paper-a", "citation_number": 1, "cited_text": "Evidence"}],
            "conversation_id": "conv-a",
        }

    with (
        patch("notebooklm_tools.services.cross_notebook._resolve_notebook_ids", return_value=[
            ("nb-a", "Notebook A"), ("nb-b", "Notebook B")
        ]),
        patch("notebooklm_tools.services.cross_notebook.chat_service.query", side_effect=answer_or_fail),
    ):
        result = cross_notebook_query(MagicMock(), "Question", all_notebooks=True)

    assert result["notebooks_succeeded"] == 1
    assert result["notebooks_failed"] == 1
    success, failure = result["results"]
    assert success["references"][0]["source_id"] == "paper-a"
    assert failure["notebook_id"] == "nb-b"
    assert failure["citations"] == {}
    assert failure["references"] == []
    assert failure["conversation_id"] is None
    assert failure["error"] == "quota exceeded"
