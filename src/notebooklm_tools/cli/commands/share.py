"""Sharing CLI commands."""

import typer
from rich.table import Table

from notebooklm_tools.cli.formatters import print_json
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import sharing as sharing_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Manage notebook sharing",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("status")
def share_status(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Show sharing status and collaborators."""
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            result = sharing_service.get_share_status(client, notebook_id)

        if json_output:
            print_json(result)
            return

        # Rich output
        console.print(f"[bold]Access:[/bold] {result['access_level'].title()}")
        if result["is_public"]:
            console.print(f"[bold]Public Link:[/bold] {result['public_link']}")

        if result["collaborators"]:
            console.print("\n[bold]Collaborators:[/bold]")
            table = Table(show_header=True, header_style="bold")
            table.add_column("Email")
            table.add_column("Role")
            table.add_column("Status")

            for c in result["collaborators"]:
                status_text = (
                    "[yellow]Pending[/yellow]" if c["is_pending"] else "[green]Active[/green]"
                )
                role_color = (
                    "blue" if c["role"] == "owner" else "cyan" if c["role"] == "editor" else "dim"
                )
                table.add_row(c["email"], f"[{role_color}]{c['role']}[/{role_color}]", status_text)

            console.print(table)
        else:
            console.print("\n[dim]No collaborators[/dim]")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("public")
def share_public(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Enable public link access (anyone with link can view)."""
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            result = sharing_service.set_public_access(client, notebook_id, is_public=True)

        console.print("[green]✓[/green] Public access enabled")
        console.print(f"[bold]Link:[/bold] {result['public_link']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("private")
def share_private(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Disable public link access (restricted to collaborators only)."""
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            sharing_service.set_public_access(client, notebook_id, is_public=False)

        console.print("[green]✓[/green] Public access disabled")
        console.print("[dim]Notebook is now restricted to collaborators[/dim]")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("invite")
def share_invite(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    email: str = typer.Argument(..., help="Email address to invite"),
    role: str = typer.Option("viewer", "--role", "-r", help="Role: viewer or editor"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Invite a collaborator by email."""
    try:
        notebook_id = get_alias_manager().resolve(notebook)
        with get_client(profile) as client:
            result = sharing_service.invite_collaborator(client, notebook_id, email, role)

        console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("batch")
def share_batch(
    notebook: str = typer.Argument(..., help="Notebook ID or alias"),
    emails: str = typer.Argument(..., help="Comma-separated email addresses"),
    role: str = typer.Option("viewer", "--role", "-r", help="Role for all: viewer or editor"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Invite multiple collaborators at once.

    Example: nlm share batch <notebook> "a@gmail.com,b@gmail.com" --role viewer
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook)

        # Parse comma-separated emails into recipients list
        email_list = [e.strip() for e in emails.split(",") if e.strip()]
        if not email_list:
            console.print("[red]Error:[/red] No valid email addresses provided.")
            raise typer.Exit(1)

        recipients = [{"email": e, "role": role} for e in email_list]

        with get_client(profile) as client:
            result = sharing_service.invite_collaborators_bulk(client, notebook_id, recipients)

        console.print(f"[green]✓[/green] {result['message']}")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Email")
        table.add_column("Role")

        for r in result["recipients"]:
            role_color = "cyan" if r["role"] == "editor" else "dim"
            table.add_row(r["email"], f"[{role_color}]{r['role']}[/{role_color}]")

        console.print(table)

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
