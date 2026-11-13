"""Export CLI commands - Export artifacts to Google Docs/Sheets."""

import typer

from notebooklm_tools.cli.formatters import print_json
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import exports as export_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Export artifacts to Google Docs/Sheets",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("artifact")
def export_artifact(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    artifact_id: str = typer.Argument(..., help="Artifact ID to export"),
    export_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Export type: 'docs' or 'sheets'",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Title for the exported document",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Export an artifact to Google Docs or Sheets.

    Examples:
        nlm export artifact NOTEBOOK_ID ARTIFACT_ID --type docs
        nlm export artifact NOTEBOOK_ID ARTIFACT_ID --type sheets --title "My Data"
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            result = export_service.export_artifact(
                client=client,
                notebook_id=notebook_id,
                artifact_id=artifact_id,
                export_type=export_type,
                title=title,
            )

        if json_output:
            print_json(result)
            return

        console.print(f"[green]✓[/green] {result['message']}")
        console.print(f"[bold]URL:[/bold] {result['url']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("to-docs")
def export_to_docs(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    artifact_id: str = typer.Argument(..., help="Artifact ID to export (Report)"),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Title for the Google Doc",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Export a Report artifact to Google Docs.

    Works with: Briefing Doc, Study Guide, Blog Post, etc.

    Example:
        nlm export to-docs NOTEBOOK_ID ARTIFACT_ID --title "My Report"
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            result = export_service.export_artifact(
                client=client,
                notebook_id=notebook_id,
                artifact_id=artifact_id,
                export_type="docs",
                title=title,
            )

        console.print(f"[green]✓[/green] {result['message']}")
        console.print(f"[bold]URL:[/bold] {result['url']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("to-sheets")
def export_to_sheets(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    artifact_id: str = typer.Argument(..., help="Artifact ID to export (Data Table)"),
    title: str | None = typer.Option(
        None,
        "--title",
        help="Title for the Google Sheet",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Export a Data Table artifact to Google Sheets.

    Example:
        nlm export to-sheets NOTEBOOK_ID ARTIFACT_ID --title "My Data Table"
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            result = export_service.export_artifact(
                client=client,
                notebook_id=notebook_id,
                artifact_id=artifact_id,
                export_type="sheets",
                title=title,
            )

        console.print(f"[green]✓[/green] {result['message']}")
        console.print(f"[bold]URL:[/bold] {result['url']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
