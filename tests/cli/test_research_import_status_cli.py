"""CLI must not recommend a blind import retry after an uncertain import."""

import pytest
from rich.console import Console

from notebooklm_tools.cli.commands import research as research_cli


@pytest.mark.parametrize(
    ("import_state", "expected", "prohibited"),
    [
        ("confirmed", "already confirmed", "nlm research import"),
        ("unconfirmed", "Reconcile existing notebook sources", "nlm research import"),
        ("guard_unavailable", "Reconcile existing notebook sources", "nlm research import"),
        ("not_requested", "nlm research import", "already confirmed"),
    ],
)
def test_cli_research_status_import_guidance(monkeypatch, import_state, expected, prohibited):
    console = Console(record=True, width=140)
    monkeypatch.setattr(research_cli, "console", console)
    status = {
        "status": "completed",
        "notebook_id": "synthetic-nb",
        "task_id": "synthetic-task",
        "sources_found": 0,
        "sources": [],
        "report": "",
        "import_state": import_state,
    }
    research_cli._display_research_status(status, compact=True)
    output = console.export_text()
    assert expected in output
    assert prohibited not in output
