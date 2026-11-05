"""Source CLI commands."""

import typer

from notebooklm_tools.cli.formatters import detect_output_format, get_formatter
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.core.alias import get_alias_manager
from notebooklm_tools.core.exceptions import NLMError
from notebooklm_tools.services import ServiceError, ValidationError
from notebooklm_tools.services import sources as sources_service

console = make_console()
app = typer.Typer(
    help="Manage sources",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("list")
def list_sources(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    full: bool = typer.Option(False, "--full", "-a", help="Show all columns"),
    drive: bool = typer.Option(
        False, "--drive", "-d", help="Show Drive sources with freshness status"
    ),
    skip_freshness: bool = typer.Option(
        False, "--skip-freshness", "-S", help="Skip freshness checks (faster, use with --drive)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Output IDs only"),
    url: bool = typer.Option(False, "--url", "-u", help="Output as ID: URL"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List sources in a notebook."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            if drive:
                sources = client.get_notebook_sources_with_types(notebook_id)
                for src in sources:
                    if skip_freshness:
                        src["is_stale"] = None
                    else:
                        src["is_fresh"] = client.check_source_freshness(src["id"])
                        src["is_stale"] = (
                            not src["is_fresh"] if src["is_fresh"] is not None else None
                        )
            else:
                sources = client.get_notebook_sources_with_types(notebook_id)

        fmt = detect_output_format(json_output, quiet, url_flag=url)
        formatter = get_formatter(fmt, console)
        formatter.format_sources(sources, full=full or drive, url_only=url)
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("add")
def add_source(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    url: list[str] | None = typer.Option(  # noqa: B008
        None, "--url", "-u", help="URL to add (repeatable for bulk)"
    ),
    text: str | None = typer.Option(None, "--text", "-t", help="Text content to add"),
    drive: str | None = typer.Option(None, "--drive", "-d", help="Google Drive document ID"),
    youtube: list[str] | None = typer.Option(  # noqa: B008
        None, "--youtube", "-y", help="YouTube URL (repeatable for bulk)"
    ),
    file: str | None = typer.Option(None, "--file", "-f", help="Local file to upload (PDF, etc.)"),
    title: str = typer.Option("", "--title", help="Title for the source"),
    doc_type: str = typer.Option("doc", "--type", help="Drive doc type: doc, slides, sheets, pdf"),
    wait: bool = typer.Option(False, "--wait", "-w", help="Wait for source processing to complete"),
    wait_timeout: float = typer.Option(
        600.0,
        "--wait-timeout",
        help="Max seconds to wait when --wait is set (default 600; raise for very long audio)",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Add a source to a notebook.

    Examples:
        nlm source add <notebook-id> --url https://example.com
        nlm source add <notebook-id> --url https://a.com --url https://b.com
        nlm source add <notebook-id> --url https://example.com --wait
        nlm source add <notebook-id> --file document.pdf --wait
        nlm source add <notebook-id> --youtube https://youtu.be/a --youtube https://youtu.be/b
    """
    notebook_id = get_alias_manager().resolve(notebook_id)

    # Normalize url list: typer gives None or a list
    urls = url or []
    if isinstance(urls, str):
        urls = [urls]
    has_url = len(urls) > 0

    # Normalize youtube list: typer gives None or a list
    youtubes = youtube or []
    if isinstance(youtubes, str):
        youtubes = [youtubes]
    has_youtube = len(youtubes) > 0

    # Validate that exactly one source type is provided (CLI-specific UX)
    source_count = sum(1 for x in [has_url, text, drive, has_youtube, file] if x)
    if source_count == 0:
        if json_output:
            handle_error(
                ValidationError(
                    "Please specify a source: --url, --text, --file, --drive, or --youtube"
                ),
                json_output=True,
            )
        console.print(
            "[red]Error:[/red] Please specify a source: --url, --text, --file, --drive, or --youtube"
        )
        raise typer.Exit(1)
    if source_count > 1:
        if json_output:
            handle_error(
                ValidationError("Please specify only one source type at a time"),
                json_output=True,
            )
        console.print("[red]Error:[/red] Please specify only one source type at a time")
        raise typer.Exit(1)

    try:
        with get_client(profile) as client:
            # Bulk URL add: multiple --url and/or --youtube flags (both are URLs to the API)
            all_urls = urls + youtubes
            if len(all_urls) > 1:
                if wait and not json_output:
                    console.print(
                        f"[blue]Adding {len(all_urls)} URLs and waiting for processing...[/blue]"
                    )
                elif not json_output:
                    console.print(f"[blue]Adding {len(all_urls)} URLs...[/blue]")
                bulk_result = sources_service.add_sources(
                    client,
                    notebook_id,
                    [{"source_type": "url", "url": u} for u in all_urls],
                    wait=wait,
                    wait_timeout=wait_timeout,
                )
                if json_output:
                    get_formatter(detect_output_format(True), console).format_item(bulk_result)
                    return
                ready_msg = " (ready)" if wait else ""
                for r in bulk_result["results"]:
                    console.print(f"[green]✓[/green] Added source: {r['title']}{ready_msg}")
                    console.print(f"[dim]  Source ID: {r['source_id']}[/dim]")
                console.print(f"\n[green]✓[/green] {bulk_result['added_count']} source(s) added.")
                return

            # Single URL add (including youtube)
            if has_youtube:
                source_type, source_url = "url", youtubes[0]
            elif has_url:
                source_type, source_url = "url", urls[0]
            else:
                source_type, source_url = None, None

            if source_type == "url":
                if wait and not json_output:
                    console.print(f"[blue]Adding {source_url} and waiting for processing...[/blue]")
                result = sources_service.add_source(
                    client,
                    notebook_id,
                    "url",
                    url=source_url,
                    wait=wait,
                    wait_timeout=wait_timeout,
                )
            elif text:
                if wait and not json_output:
                    console.print("[blue]Adding text and waiting for processing...[/blue]")
                result = sources_service.add_source(
                    client,
                    notebook_id,
                    "text",
                    text=text,
                    title=title or None,
                    wait=wait,
                    wait_timeout=wait_timeout,
                )
            elif drive:
                if wait and not json_output:
                    console.print(
                        "[blue]Adding Drive document and waiting for processing...[/blue]"
                    )
                result = sources_service.add_source(
                    client,
                    notebook_id,
                    "drive",
                    document_id=drive,
                    title=title or None,
                    doc_type=doc_type,
                    wait=wait,
                    wait_timeout=wait_timeout,
                )
            elif file:
                from pathlib import Path

                file_path = Path(file).expanduser().resolve()
                if not file_path.exists():
                    if json_output:
                        handle_error(
                            ValidationError(f"File not found: {file}"),
                            json_output=True,
                        )
                    console.print(f"[red]Error:[/red] File not found: {file}")
                    raise typer.Exit(1)
                if not json_output:
                    console.print(
                        f"[blue]Uploading {file_path.name}{'...' if not wait else ' and waiting for processing...'}[/blue]"
                    )
                result = sources_service.add_source(
                    client,
                    notebook_id,
                    "file",
                    file_path=str(file_path),
                    title=title or None,
                    wait=wait,
                    wait_timeout=wait_timeout,
                )
            else:
                raise typer.Exit(1)

        # Show result
        if json_output:
            get_formatter(detect_output_format(True), console).format_item(result)
            return
        ready_msg = " (ready)" if wait else ""
        console.print(f"[green]✓[/green] Added source: {result['title']}{ready_msg}")
        console.print(f"[dim]Source ID: {result['source_id']}[/dim]")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("get")
def get_source(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Get source details."""
    try:
        source_id = get_alias_manager().resolve(source_id)
        with get_client(profile) as client:
            source = client.get_source_fulltext(source_id)

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_item(source, title="Source Details")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("describe")
def describe_source(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Get AI-generated source summary with keywords."""
    try:
        source_id = get_alias_manager().resolve(source_id)
        with get_client(profile) as client:
            summary = client.get_source_guide(source_id)

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_item(summary, title="Source Summary")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("content")
def get_source_content(
    source_id: str = typer.Argument(..., help="Source ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    output: str | None = typer.Option(None, "--output", "-o", help="Write content to file"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Get raw source content (no AI processing)."""
    try:
        source_id = get_alias_manager().resolve(source_id)
        with get_client(profile) as client:
            content = client.get_source_fulltext(source_id)

        if output:
            from pathlib import Path

            Path(output).write_text(content["content"], encoding="utf-8")
            console.print(
                f"[green]✓[/green] Wrote {content['char_count']:,} characters to {output}"
            )
        else:
            fmt = detect_output_format(json_output)
            formatter = get_formatter(fmt, console)
            formatter.format_item(content, title="Source Content")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("rename")
def rename_source(
    source_id: str = typer.Argument(..., help="Source ID"),
    title: str = typer.Argument(..., help="New title"),
    notebook_id: str = typer.Option(
        ..., "--notebook", "-n", help="Notebook ID containing the source"
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Rename a source."""
    source_id = get_alias_manager().resolve(source_id)
    notebook_id = get_alias_manager().resolve(notebook_id)

    try:
        with get_client(profile) as client:
            result = sources_service.rename_source(client, notebook_id, source_id, title)
        console.print(f"[green]✓[/green] Renamed source to: {result['title']}")
        console.print(f"[dim]Source ID: {result['source_id']}[/dim]")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("delete")
def delete_source(
    source_ids: list[str] = typer.Argument(..., help="Source ID(s) to delete"),  # noqa: B008
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Delete source(s) permanently.

    Accepts one or more source IDs for single or bulk deletion.

    Examples:
        nlm source delete <source-id> --confirm
        nlm source delete <id1> <id2> <id3> --confirm
    """
    resolved_ids = [get_alias_manager().resolve(sid) for sid in source_ids]

    if not confirm:
        if len(resolved_ids) == 1:
            typer.confirm(
                f"Are you sure you want to delete source {resolved_ids[0]}?",
                abort=True,
            )
        else:
            typer.confirm(
                f"Are you sure you want to delete {len(resolved_ids)} sources?",
                abort=True,
            )

    try:
        with get_client(profile) as client:
            if len(resolved_ids) == 1:
                sources_service.delete_source(client, resolved_ids[0])
            else:
                sources_service.delete_sources(client, resolved_ids)
        if json_output:
            get_formatter(detect_output_format(True), console).format_item(
                {
                    "status": "success",
                    "deleted_source_ids": resolved_ids,
                    "deleted_count": len(resolved_ids),
                }
            )
        elif len(resolved_ids) == 1:
            console.print(f"[green]✓[/green] Deleted source: {resolved_ids[0]}")
        else:
            console.print(f"[green]✓[/green] Deleted {len(resolved_ids)} sources")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("stale")
def list_stale_sources(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List Drive sources that need syncing."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            listing = sources_service.list_drive_sources(client, notebook_id)

        drive_sources = listing["drive_sources"]
        stale_sources = [{**s, "is_stale": True} for s in drive_sources if s.get("stale") is True]
        unknown_sources = [s for s in drive_sources if s.get("stale") is None]

        if not stale_sources:
            if unknown_sources:
                console.print(
                    f"[yellow]?[/yellow] Freshness unavailable for "
                    f"{len(unknown_sources)} Drive source(s); none confirmed stale."
                )
            else:
                console.print("[green]✓[/green] All Drive sources are up to date.")
            return

        console.print(f"[yellow]⚠[/yellow] {len(stale_sources)} source(s) need syncing:")
        if unknown_sources:
            console.print(
                f"[yellow]?[/yellow] Freshness unknown for "
                f"{len(unknown_sources)} other Drive source(s)."
            )

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_sources(stale_sources, full=True)

        console.print("\n[dim]Run 'nlm source sync <notebook-id>' to sync all stale sources.[/dim]")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("sync")
def sync_sources(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    source_ids: str | None = typer.Option(
        None,
        "--source-ids",
        "-s",
        help="Comma-separated source IDs to sync (default: all stale)",
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Sync Drive sources with latest content."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        unknown_count = 0

        with get_client(profile) as client:
            if source_ids:
                ids_to_sync = [
                    get_alias_manager().resolve(sid.strip()) for sid in source_ids.split(",")
                ]
            else:
                listing = sources_service.list_drive_sources(client, notebook_id)
                ids_to_sync = [
                    s["id"]
                    for s in listing["drive_sources"]
                    if s.get("stale") is True and s.get("can_sync") is True and s.get("id")
                ]
                unknown_count = sum(s.get("stale") is None for s in listing["drive_sources"])

        if not ids_to_sync:
            if not source_ids and unknown_count:
                console.print(
                    f"[yellow]?[/yellow] No confirmed stale/syncable sources; "
                    f"freshness unknown for {unknown_count} Drive source(s)."
                )
            else:
                console.print("[green]✓[/green] No sources need syncing.")
            return

        if not confirm:
            typer.confirm(
                f"Sync {len(ids_to_sync)} source(s)?",
                abort=True,
            )

        with get_client(profile) as client:
            results = sources_service.sync_drive_sources(client, ids_to_sync)

        synced = sum(1 for r in results if r.get("synced"))
        console.print(f"[green]✓[/green] Synced {synced} source(s)")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))
