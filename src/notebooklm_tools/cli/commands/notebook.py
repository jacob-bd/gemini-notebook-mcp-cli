"""Notebook CLI commands."""

import typer

from notebooklm_tools.cli.formatters import detect_output_format, get_formatter
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import (
    ServiceError,
)
from notebooklm_tools.services import (
    chat as chat_service,
)
from notebooklm_tools.services import (
    notebooks as notebooks_service,
)
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Manage notebooks",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("list")
def list_notebooks(
    full: bool = typer.Option(False, "--full", "-a", help="Show all columns"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Output IDs only"),
    title: bool = typer.Option(False, "--title", "-t", help="Show ID: Title format"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List all notebooks."""
    try:
        with get_client(profile) as client:
            notebooks = client.list_notebooks()

        fmt = detect_output_format(json_output, quiet, title)
        formatter = get_formatter(fmt, console)
        formatter.format_notebooks(notebooks, full=full, title_only=title)
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("create")
def create_notebook(
    title: str = typer.Argument("", help="Notebook title"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a new notebook."""
    try:
        with get_client(profile) as client:
            result = notebooks_service.create_notebook(client, title)

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_item(result, title="Notebook Created")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=json_output)


@app.command("get")
def get_notebook(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Get notebook details."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notebooks_service.get_notebook(client, notebook_id)

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_item(result, title="Notebook Details")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("describe")
def describe_notebook(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Get AI-generated notebook summary with suggested topics."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notebooks_service.describe_notebook(client, notebook_id)

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_item(result, title="Notebook Summary")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("rename")
def rename_notebook(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    new_title: str = typer.Argument(..., help="New title"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Rename a notebook."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = notebooks_service.rename_notebook(client, notebook_id, new_title)

        console.print(f"[green]✓[/green] {result['message']}")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("delete")
def delete_notebook(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Delete a notebook permanently."""
    notebook_id = get_alias_manager().resolve(notebook_id)

    if not confirm:
        typer.confirm(
            f"Are you sure you want to delete notebook {notebook_id}?",
            abort=True,
        )

    try:
        with get_client(profile) as client:
            result = notebooks_service.delete_notebook(client, notebook_id)

        if json_output:
            get_formatter(detect_output_format(True), console).format_item(result)
        else:
            console.print(f"[green]✓[/green] {result['message']}")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("query")
def query_notebook(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    question: str = typer.Argument(..., help="Question to ask"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    conversation_id: str | None = typer.Option(
        None,
        "--conversation-id",
        "-c",
        help="Conversation ID for follow-up questions",
    ),
    source_ids: str | None = typer.Option(
        None,
        "--source-ids",
        "-s",
        help="Comma-separated source IDs to query (default: all)",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        "-t",
        help="Query timeout in seconds (default: 120; source-heavy notebooks may need 180+)",
    ),
    new_conversation: bool = typer.Option(
        False,
        "--new-conversation",
        help="Start a fresh conversation instead of reusing the notebook's chat",
    ),
) -> None:
    """Chat with notebook sources."""
    try:
        sources = source_ids.split(",") if source_ids else None
        notebook_id = get_alias_manager().resolve(notebook_id)

        with get_client(profile) as client:
            result = chat_service.query(
                client,
                notebook_id,
                question,
                source_ids=sources,
                conversation_id=conversation_id,
                timeout=timeout,
                new_conversation=new_conversation,
            )

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_item(result, title="Query Response")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
