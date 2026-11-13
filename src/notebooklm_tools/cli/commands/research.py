"""Research CLI commands."""

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import research as research_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Research and discover sources",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("start")
def start_research(
    query: str = typer.Argument(..., help="What to search for"),
    source: str = typer.Option(
        "web",
        "--source",
        "-s",
        help="Where to search: web or drive",
    ),
    mode: str = typer.Option(
        "fast",
        "--mode",
        "-m",
        help="Research mode: fast (~30s, ~10 sources) or deep (~5min, ~40 sources, web only)",
    ),
    notebook_id: str | None = typer.Option(
        None,
        "--notebook-id",
        "-n",
        help="Add to existing notebook",
    ),
    title: str | None = typer.Option(
        None,
        "--title",
        "-t",
        help="Title for new notebook",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Start new research even if one is already pending",
    ),
    auto_import: bool = typer.Option(
        False,
        "--auto-import",
        "--wait-and-import",
        help="Wait for completion and automatically import sources",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """
    Start a research task to find new sources.

    This searches the web or Google Drive to discover relevant sources
    for your research topic. Use 'nlm research status' to check progress
    and 'nlm research import' to add discovered sources to your notebook.
    """
    try:
        if not notebook_id and not title:
            console.print("[red]Error:[/red] Either --notebook-id or --title is required")
            raise typer.Exit(1)

        if notebook_id:
            notebook_id = get_alias_manager().resolve(notebook_id)

        with get_client(profile) as client:
            if not notebook_id and title:
                from notebooklm_tools.services import notebooks as notebook_service

                nb_result = notebook_service.create_notebook(client, title=title)
                notebook_id = nb_result["notebook_id"]
                console.print(f"[green]✓[/green] Created new notebook: {title}")

            # Check for existing research before starting new one (CLI-only UX)
            if not force:
                existing = client.poll_research(notebook_id)
                if existing and existing.get("status") == "in_progress":
                    console.print(
                        "[yellow]Warning:[/yellow] Research already in progress for this notebook."
                    )
                    console.print(f"  Task ID: {existing.get('task_id', 'unknown')}")
                    console.print(f"  Sources found so far: {existing.get('source_count', 0)}")
                    console.print(
                        "\n[dim]Use --force to start a new research anyway (will overwrite pending results).[/dim]"
                    )
                    console.print(
                        "[dim]Or run 'nlm research status' to check progress / 'nlm research import' to save results.[/dim]"
                    )
                    raise typer.Exit(1)
                elif (
                    existing
                    and existing.get("status") == "completed"
                    and existing.get("source_count", 0) > 0
                ):
                    console.print(
                        "[yellow]Warning:[/yellow] Previous research completed with sources not yet imported."
                    )
                    console.print(f"  Task ID: {existing.get('task_id', 'unknown')}")
                    console.print(f"  Sources available: {existing.get('source_count', 0)}")
                    console.print(
                        "\n[dim]Starting new research will discard existing results.[/dim]"
                    )
                    console.print(
                        "[dim]Run 'nlm research import' first to save them, or proceed to overwrite.[/dim]"
                    )
                    typer.confirm("Continue and start new research?", abort=True)

            result = research_service.start_research(
                client,
                notebook_id,
                query,
                source=source,
                mode=mode,
            )

        console.print("[green]✓[/green] Research started")
        console.print(f"  Query: {query}")
        console.print(f"  Source: {source}")
        console.print(f"  Mode: {mode}")
        console.print(f"  Notebook ID: {notebook_id}")
        console.print(f"  Task ID: {result['task_id']}")

        if auto_import:
            console.print("\n[dim]Waiting for research to complete...[/dim]")

            # Use progress indicator from status command
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Gathering sources...", total=None)

                with get_client(profile) as import_client:
                    poll_res = research_service.poll_research(
                        import_client,
                        notebook_id,
                        task_id=result["task_id"],
                        poll_interval=30,
                        max_wait=900,
                    )

            _display_research_status(poll_res, compact=True)

            if poll_res["status"] == "completed":
                console.print("\n[dim]Importing discovered sources...[/dim]")
                with get_client(profile) as import_client:
                    import_res = research_service.import_research(
                        import_client, notebook_id, poll_res["task_id"]
                    )
                console.print(f"[green]✓[/green] {import_res['message']}")
                for src in import_res.get("imported_sources", []):
                    title = (
                        src.get("title", "Unknown")
                        if isinstance(src, dict)
                        else getattr(src, "title", "Unknown")
                    )
                    console.print(f"  • {title}")
            else:
                console.print(
                    "[yellow]Warning:[/yellow] Could not auto-import. Research may have timed out or failed."
                )
        else:
            estimate = "~30 seconds" if mode == "fast" else "~5 minutes"
            console.print(f"\n[dim]Estimated time: {estimate}[/dim]")
            console.print(f"[dim]Run 'nlm research status {notebook_id}' to check progress.[/dim]")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("status")
def check_status(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    task_id: str | None = typer.Option(None, "--task-id", "-t", help="Specific task ID to check"),
    compact: bool = typer.Option(
        True,
        "--compact/--full",
        help="Show compact or full details",
    ),
    poll_interval: int = typer.Option(
        30,
        "--poll-interval",
        help="Seconds between status checks",
    ),
    max_wait: int = typer.Option(
        300,
        "--max-wait",
        help="Maximum seconds to wait (0 for single check)",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """
    Check research task progress.

    By default, polls until the task completes or times out.
    Use --max-wait 0 for a single status check.
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        if task_id:
            task_id = get_alias_manager().resolve(task_id)

        # Polling loop is a CLI-only presentation concern (progress spinners)
        if max_wait > 0:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Waiting for research to complete...", total=None)

                import time

                elapsed = 0
                with get_client(profile) as client:
                    while elapsed < max_wait:
                        result = research_service.poll_research(
                            client,
                            notebook_id,
                            task_id=task_id,
                            compact=compact,
                        )
                        if result["status"] == "completed":
                            break
                        time.sleep(poll_interval)
                        elapsed += poll_interval
        else:
            with get_client(profile) as client:
                result = research_service.poll_research(
                    client,
                    notebook_id,
                    task_id=task_id,
                    compact=compact,
                )

        _display_research_status(result, compact)

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


def _display_research_status(result: dict, compact: bool) -> None:
    """Display research status in a formatted way (presentation-only helper)."""
    status = result["status"]
    sources = result.get("sources", [])
    report = result.get("report", "")

    status_style = {
        "completed": "green",
        "pending": "yellow",
        "running": "yellow",
        "in_progress": "yellow",
        "no_research": "dim",
        "failed": "red",
    }.get(status, "")

    console.print("\n[bold]Research Status:[/bold]")

    if status == "no_research":
        console.print("  Status: [dim]no research found[/dim]")
        console.print("\n[dim]Start a research task with 'nlm research start'.[/dim]")
        return

    if status_style:
        console.print(f"  Status: [{status_style}]{status}[/{status_style}]")
    else:
        console.print(f"  Status: {status}")

    task_id_val = result.get("task_id", "")
    if task_id_val:
        console.print(f"  Task ID: [cyan]{task_id_val}[/cyan]")
    console.print(f"  Sources found: {result.get('sources_found', 0)}")

    if report and not compact:
        console.print("\n[bold]Report:[/bold]")
        console.print(report)

    if sources and not compact:
        console.print("\n[bold]Discovered Sources:[/bold]")
        for i, src in enumerate(sources):
            if isinstance(src, dict):
                title = src.get("title", "Untitled")
                url = src.get("url", "")
            else:
                title = getattr(src, "title", "Untitled")
                url = getattr(src, "url", "")
            console.print(f"  [{i}] {title}")
            if url:
                console.print(f"      [dim]{url}[/dim]")

    if status == "completed":
        nb_id = result.get("notebook_id", "")
        console.print(
            f"\n[dim]Run 'nlm research import {nb_id} <task-id>' to import sources.[/dim]"
        )


@app.command("import")
def import_research(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    task_id: str | None = typer.Argument(
        None, help="Research task ID (auto-detects if not provided)"
    ),
    indices: str | None = typer.Option(
        None,
        "--indices",
        "-i",
        help="Comma-separated indices of sources to import (default: all)",
    ),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        "-t",
        help="Import timeout in seconds (default: 300)",
    ),
    cited_only: bool = typer.Option(
        False,
        "--cited-only",
        help="Import only sources cited by the research report (overrides --indices)",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """
    Import discovered sources from a completed research task.

    If TASK_ID is not provided, automatically imports from the first
    available completed or in-progress research task.
    """
    try:
        source_indices = None
        if indices:
            source_indices = [int(i.strip()) for i in indices.split(",")]

        notebook_id = get_alias_manager().resolve(notebook_id)

        with get_client(profile) as client:
            # Auto-detect task ID if not provided (CLI-only UX convenience)
            if not task_id:
                research = client.poll_research(notebook_id)
                if not research or research.get("status") == "no_research":
                    console.print("[red]Error:[/red] No research tasks found for this notebook.")
                    console.print(
                        "[dim]Start a research task first with 'nlm research start'.[/dim]"
                    )
                    raise typer.Exit(1)

                task_id = research.get("task_id")
                if not task_id:
                    tasks = research.get("tasks", [])
                    if tasks:
                        task_id = tasks[0].get("task_id")

                if not task_id:
                    console.print("[red]Error:[/red] Could not determine task ID.")
                    raise typer.Exit(1)

                console.print(f"[dim]Using task: {task_id}[/dim]")
            else:
                task_id = get_alias_manager().resolve(task_id)

            result = research_service.import_research(
                client,
                notebook_id,
                task_id,
                source_indices=source_indices,
                timeout=timeout,
                cited_only=cited_only,
            )

        console.print(f"[green]✓[/green] {result['message']}")
        for src in result.get("imported_sources", []):
            if isinstance(src, dict):
                console.print(f"  • {src.get('title', 'Unknown')}")
            else:
                console.print(f"  • {getattr(src, 'title', 'Unknown')}")
    except ValueError:
        console.print("[red]Error:[/red] Invalid indices. Use comma-separated numbers like: 0,2,5")
        raise typer.Exit(1) from None
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
