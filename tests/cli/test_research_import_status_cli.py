"""CLI must not recommend a blind import retry after an uncertain import."""

from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

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


@pytest.mark.parametrize(
    ("import_state", "expected_exit"),
    [("confirmed", 0), ("unconfirmed", 1), ("guard_unavailable", 1)],
)
def test_start_auto_import_uses_one_shot_status_not_manual_import(import_state, expected_exit):
    """Starting research must never bypass the guarded service import path."""
    alias = MagicMock()
    alias.resolve.return_value = "synthetic-nb"
    client = MagicMock()
    client.__enter__.return_value = client
    client.poll_research.return_value = None
    state = {
        "status": "completed",
        "notebook_id": "synthetic-nb",
        "task_id": "provider-renamed-task",
        "sources_found": 0,
        "sources": [],
        "report": "",
        "import_state": import_state,
    }
    with (
        patch.object(research_cli, "get_alias_manager", return_value=alias),
        patch.object(research_cli, "get_client", return_value=client),
        patch.object(
            research_cli.research_service,
            "start_research",
            return_value={"task_id": "original-task-id"},
        ),
        patch.object(research_cli.research_service, "poll_research", return_value=state) as poll,
        patch.object(research_cli.research_service, "import_research") as manual_import,
    ):
        result = CliRunner().invoke(
            research_cli.app,
            [
                "start",
                "synthetic query",
                "--notebook-id",
                "synthetic-nb",
                "--force",
                "--auto-import",
            ],
        )
    assert result.exit_code == expected_exit, result.output
    manual_import.assert_not_called()
    poll.assert_called_once()
    assert poll.call_args.kwargs["task_id"] == "original-task-id"
    assert poll.call_args.kwargs["auto_import"] is True
