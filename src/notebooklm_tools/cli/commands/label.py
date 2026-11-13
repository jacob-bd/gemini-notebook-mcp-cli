"""Label CLI commands - manage source labels in a notebook."""

import typer
from rich.table import Table

from notebooklm_tools.cli.formatters import print_json
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import labels as labels_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Manage source labels in a notebook",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def _print_labels_table(labels: list[dict], notebook_id: str) -> None:
    if not labels:
        console.print(f"[dim]No labels found in notebook {notebook_id}[/dim]")
        return
    table = Table(title=f"Labels in Notebook {notebook_id}")
    table.add_column("Emoji", style="yellow", width=6)
    table.add_column("Name", style="green")
    table.add_column("Label ID", style="cyan", no_wrap=True)
    table.add_column("Sources", style="white", justify="right")
    for lbl in labels:
        table.add_row(
            lbl.get("emoji") or "",
            lbl.get("name", ""),
            lbl.get("id", "")[:8] + "...",
            str(len(lbl.get("source_ids", []))),
        )
    console.print(table)
    console.print(f"\n[dim]Total: {len(labels)} label(s)[/dim]")


@app.command("auto")
def auto_label(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Auto-label sources using AI-generated thematic categories.

    Requires 5+ sources. If labels already exist, returns current labels.
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.auto_label(client, notebook_id)

        if json_output:
            print_json(result)
        else:
            _print_labels_table(result["labels"], notebook_id)

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("list")
def list_labels(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Output label IDs only"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List current labels in a notebook.

    Note: If no labels exist, this will trigger AI auto-labeling.
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.list_labels(client, notebook_id)

        labels = result["labels"]

        if quiet:
            for lbl in labels:
                console.print(lbl["id"])
        elif json_output:
            print_json(result)
        else:
            _print_labels_table(labels, notebook_id)

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("reorganize")
def reorganize_labels(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    unlabeled_only: bool = typer.Option(
        False, "--unlabeled", "-u", help="Only label sources not yet in any label"
    ),
    confirm: bool = typer.Option(
        False, "--confirm", "-y", help="Skip confirmation prompt (all-sources mode)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Force AI re-categorization of sources into new labels.

    By default, replaces ALL existing labels (destructive). Use --unlabeled to
    only label sources that are not yet in any label.
    """
    if not unlabeled_only and not confirm:
        confirmed = typer.confirm(
            "Reorganize all sources? This will NOT preserve existing labels.",
            default=False,
        )
        if not confirmed:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)

    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.reorganize_labels(client, notebook_id, unlabeled_only)

        if json_output:
            print_json({"status": "success", **result})
        else:
            scope = "unlabeled sources" if unlabeled_only else "all sources"
            console.print(f"[green]✓[/green] Reorganized {scope}.")
            _print_labels_table(result["labels"], notebook_id)

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("create")
def create_label(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    name: str = typer.Argument(..., help="Label display name"),
    emoji: str = typer.Option("", "--emoji", "-e", help="Optional emoji marker (e.g. 📊)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a new empty label manually."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.create_label(client, notebook_id, name, emoji)

        if json_output:
            print_json({"status": "success", **result})
        else:
            console.print(f"[green]✓[/green] {result['message']}")
            if result.get("label_id"):
                console.print(f"  Label ID: {result['label_id']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("rename")
def rename_label(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    label_id: str = typer.Argument(..., help="Label UUID to rename"),
    new_name: str = typer.Argument(..., help="New display name"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Rename an existing label."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.rename_label(client, notebook_id, label_id, new_name)

        if json_output:
            print_json({"status": "success", **result})
        else:
            console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("emoji")
def set_emoji(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    label_id: str = typer.Argument(..., help="Label UUID"),
    emoji: str = typer.Argument(..., help='Emoji character (use "" to clear)'),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Set or clear the emoji marker on a label."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.set_label_emoji(client, notebook_id, label_id, emoji)

        if json_output:
            print_json({"status": "success", **result})
        else:
            console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("move")
def move_source(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    source_id: str = typer.Argument(..., help="Source UUID to assign"),
    label_id: str = typer.Argument(..., help="Target label UUID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Assign a source to a label.

    Sources support multi-label assignment — this adds the source to the
    target label without removing it from other labels.
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.move_source_to_label(client, notebook_id, label_id, source_id)

        if json_output:
            print_json({"status": "success", **result})
        else:
            console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("delete")
def delete_label(
    notebook_id: str = typer.Argument(..., help="Notebook ID or alias"),
    label_id: str = typer.Argument(..., help="Label UUID to delete"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Confirm deletion without prompt"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Delete a label permanently. Sources are NOT deleted."""
    if not confirm:
        confirmed = typer.confirm(
            f"Delete label {label_id[:8]}...? Sources will be preserved.",
            default=False,
        )
        if not confirmed:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)

    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = labels_service.delete_labels(client, notebook_id, [label_id])

        if json_output:
            print_json({"status": "success", **result})
        else:
            console.print(f"[green]✓[/green] {result['message']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
