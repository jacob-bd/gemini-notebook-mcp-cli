"""Note CLI commands."""

import typer
from rich.table import Table

from notebooklm_tools.cli.formatters import print_json
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import notes as notes_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Manage notes",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("list")
def list_notes(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Output IDs only"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List all notes in a notebook."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notes_service.list_notes(client, notebook_id)

        notes = result["notes"]

        if quiet:
            for note in notes:
                console.print(note["id"])
        elif json_output:
            print_json(result)
        else:
            if not notes:
                console.print(f"[dim]No notes found in notebook {notebook_id}[/dim]")
                return

            table = Table(title=f"Notes in Notebook {notebook_id}")
            table.add_column("ID", style="cyan", no_wrap=True)
            table.add_column("Title", style="green")
            table.add_column("Preview", style="white")

            for note in notes:
                preview = note.get("preview", "")[:100]
                if len(preview) == 100:
                    preview += "..."
                table.add_row(note["id"][:8] + "...", note.get("title", "Untitled"), preview)

            console.print(table)
            console.print(f"\n[dim]Total: {result['count']} note(s)[/dim]")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("create")
def create_note(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    content: str = typer.Option(..., "--content", "-c", help="Note content"),
    title: str = typer.Option("New Note", "--title", "-t", help="Note title"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a new note in a notebook."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notes_service.create_note(client, notebook_id, content, title)

        console.print(f"[green]✓[/green] Note created: {result['note_id']}")
        console.print(f"  Title: {result['title']}")
        console.print(f"  Preview: {result['content_preview']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("update")
def update_note(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    note_id: str = typer.Argument(..., help="Note ID"),
    content: str | None = typer.Option(None, "--content", "-c", help="New content"),
    title: str | None = typer.Option(None, "--title", "-t", help="New title"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Update a note's content or title."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notes_service.update_note(client, notebook_id, note_id, content, title)

        console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("delete")
def delete_note(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    note_id: str = typer.Argument(..., help="Note ID to delete"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Delete a note permanently."""
    if not confirm:
        confirmed = typer.confirm(f"Delete note {note_id}? This action is IRREVERSIBLE.")
        if not confirmed:
            console.print("[dim]Cancelled[/dim]")
            raise typer.Exit(0)

    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notes_service.delete_note(client, notebook_id, note_id)

        console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
