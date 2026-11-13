"""CLI commands for notebook chat sessions (nlm chats / nlm chat)."""

import typer
from rich.console import Console
from rich.table import Table

from notebooklm_tools.cli.formatters import print_json
from notebooklm_tools.cli.utils import handle_error
from notebooklm_tools.services import ServiceError, chats
from notebooklm_tools.services.errors import NLMError

console = Console()
chats_app = typer.Typer(
    name="chats",
    help="List, view, export, and delete chat sessions for a notebook.",
    no_args_is_help=True,
)


@chats_app.command("list")
def chats_list(
    notebook: str = typer.Argument(..., help="Notebook ID or title alias"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max chat sessions to display"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile name"),
) -> None:
    """List chat sessions for a notebook."""
    try:
        data = chats.list_chat_sessions(notebook=notebook, limit=limit, profile=profile)
        if json_output:
            print_json(data)
            return

        sessions = data.get("sessions", [])
        if not sessions:
            console.print(
                f"[yellow]No chat sessions found for '{data['notebook_title']}'.[/yellow]"
            )
            return

        table = Table(title=f"Chat Sessions — {data['notebook_title']}")
        table.add_column("Session ID", style="cyan")
        table.add_column("Turns", justify="right", style="green")
        table.add_column("Preview / First Query", style="white")

        for s in sessions:
            table.add_row(
                s["conversation_id"],
                str(s["turn_count"]),
                s["preview"],
            )

        console.print(table)
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=json_output)


@chats_app.command("get")
def chats_get(
    notebook: str = typer.Argument(..., help="Notebook ID or title alias"),
    conversation_id: str | None = typer.Argument(None, help="Conversation ID (defaults to latest)"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile name"),
) -> None:
    """Get full transcript of a chat session."""
    try:
        data = chats.get_chat_session(
            notebook=notebook, conversation_id=conversation_id, profile=profile
        )
        if json_output:
            print_json(data)
            return

        console.print(f"\n[bold cyan]Chat Session — {data['notebook_title']}[/bold cyan]")
        console.print(
            f"[dim]Session ID: {data['conversation_id']} | Turns: {data['turn_count']}[/dim]\n"
        )

        for turn in data.get("transcript", []):
            t_num = turn.get("turn", 1)
            q = turn.get("query", "")
            a = turn.get("answer", "")
            console.print(f"[bold yellow]Turn {t_num} User:[/bold yellow] {q}")
            console.print(f"[bold green]NotebookLM:[/bold green] {a}\n")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=json_output)


@chats_app.command("export")
def chats_export(
    notebook: str = typer.Argument(..., help="Notebook ID or title alias"),
    conversation_id: str | None = typer.Option(
        None, "--conversation-id", "-c", help="Conversation ID"
    ),
    format: str = typer.Option("md", "--format", "-f", help="Export format: md or json"),
    output: str | None = typer.Option(None, "--output", "-o", help="File path to save export"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile name"),
) -> None:
    """Export a chat transcript to Markdown or JSON."""
    try:
        data = chats.export_chat_session(
            notebook=notebook,
            conversation_id=conversation_id,
            format=format,
            output_file=output,
            profile=profile,
        )
        if output:
            console.print(
                f"[green]✓[/green] Exported chat transcript to [cyan]{data['file_path']}[/cyan]"
            )
        else:
            console.print(data["content"])
    except (ServiceError, NLMError) as e:
        handle_error(e)


@chats_app.command("to-note")
def chats_to_note(
    notebook: str = typer.Argument(..., help="Notebook ID or title alias"),
    conversation_id: str = typer.Argument(..., help="Conversation ID"),
    turn: int | None = typer.Option(
        None, "--turn", "-t", help="1-indexed turn to save (default: entire chat)"
    ),
    title: str | None = typer.Option(None, "--title", help="Note title"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile name"),
) -> None:
    """Save a chat turn or full chat session as a Note in the notebook."""
    try:
        data = chats.save_chat_to_note(
            notebook=notebook,
            conversation_id=conversation_id,
            turn_index=turn,
            title=title,
            profile=profile,
        )
        if json_output:
            print_json(data)
            return
        console.print(f"[green]✓[/green] Saved chat to note [cyan]{data.get('note_id', '')}[/cyan]")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=json_output)


@chats_app.command("delete")
def chats_delete(
    notebook: str = typer.Argument(..., help="Notebook ID or title alias"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile name"),
) -> None:
    """Permanently delete all chat history for a notebook."""
    if not confirm:
        typer.confirm(
            f"Permanently delete all chat history for notebook '{notebook}'?",
            abort=True,
        )

    try:
        data = chats.delete_chat_history(notebook=notebook, profile=profile)
        if json_output:
            print_json(data)
            return
        console.print(
            f"[green]✓[/green] Deleted chat history for [cyan]{data['notebook_title']}[/cyan]."
        )
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=json_output)
