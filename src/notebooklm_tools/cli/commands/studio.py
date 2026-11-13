"""Studio CLI commands for generation (audio, report, quiz, etc.)."""

import json
from pathlib import Path

import typer
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn

from notebooklm_tools.cli.formatters import detect_output_format, get_formatter, print_json
from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError, ValidationError
from notebooklm_tools.services import notebooks as notebooks_service
from notebooklm_tools.services import studio as studio_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError
from notebooklm_tools.utils.config import get_default_language

console = make_console()

# Main studio app for status/delete
app = typer.Typer(
    help="Manage studio artifacts",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Individual generation apps
audio_app = typer.Typer(
    help="Create audio overviews",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
report_app = typer.Typer(
    help="Create reports",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
quiz_app = typer.Typer(
    help="Create quizzes",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
flashcards_app = typer.Typer(
    help="Create flashcards",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
mindmap_app = typer.Typer(
    help="Create and manage mind maps",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
slides_app = typer.Typer(
    help="Create slide decks",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
infographic_app = typer.Typer(
    help="Create infographics",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
video_app = typer.Typer(
    help="Create video overviews",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
data_table_app = typer.Typer(
    help="Create data tables",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def parse_source_ids(source_ids: str | None) -> list[str] | None:
    """Parse comma-separated source IDs."""
    if source_ids:
        return [get_alias_manager().resolve(s.strip()) for s in source_ids.split(",")]
    return None


def _run_create(
    notebook_id: str,
    artifact_type: str,
    label: str,
    profile: str | None,
    json_output: bool = False,
    **kwargs,
) -> None:
    """Shared CLI creation logic: spinner + service call + formatted output.

    CLI-specific concerns (confirmation, arg parsing) happen in each command.
    This helper handles the common pattern of spinner → create → print result.
    """
    if not kwargs.get("language"):
        kwargs["language"] = get_default_language()

    try:
        notebook_id = get_alias_manager().resolve(notebook_id)

        def create() -> dict:
            with get_client(profile) as client:
                return studio_service.create_artifact(
                    client,
                    notebook_id,
                    artifact_type,
                    **kwargs,
                )

        if json_output:
            result = create()
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task(f"Creating {label}...", total=None)
                result = create()

        # Mind map has a different result shape
        if json_output:
            get_formatter(detect_output_format(True), console).format_item(result)
        elif artifact_type == "mind_map":
            console.print("[green]✓[/green] Mind map created")
            console.print(f"  ID: {result.get('artifact_id', 'unknown')}")
            console.print(f"  Title: {result.get('title', 'Mind Map')}")
        else:
            console.print(f"[green]✓[/green] {label.title()} generation started")
            console.print(f"  Artifact ID: {result.get('artifact_id', 'unknown')}")
            console.print(f"\n[dim]Run 'nlm studio status {notebook_id}' to check progress.[/dim]")
    except (ValidationError, ServiceError) as e:
        if json_output:
            handle_error(e, json_output=True)
        msg = e.user_message if isinstance(e, ServiceError) else str(e)
        console.print(f"[red]Error:[/red] {msg}")
        if isinstance(e, ServiceError) and "rejected" in str(e):
            console.print("[dim]Try again later or create from NotebookLM UI for diagnosis.[/dim]")
        raise typer.Exit(1) from e
    except NLMError as e:
        handle_error(e, json_output=json_output)


# ========== Studio Status/Delete ==========


@app.command("status")
def studio_status(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    full: bool = typer.Option(False, "--full", "-a", help="Show all details"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    mcp_compatible: bool = typer.Option(
        False,
        "--mcp-compatible",
        help="Use the MCP status envelope and artifact_id field",
    ),
    artifact_id: str | None = typer.Option(
        None,
        "--artifact-id",
        help="Return only one artifact",
    ),
    limit: int | None = typer.Option(None, "--limit", help="Maximum artifacts to return (1-100)"),
    offset: int = typer.Option(0, "--offset", help="Artifacts to skip"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List all studio artifacts and their status (including mind maps)."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        effective_limit = limit if limit is not None else (20 if mcp_compatible else None)
        with get_client(profile) as client:
            result = studio_service.get_studio_status(
                client,
                notebook_id,
                artifact_id=artifact_id,
                include_details=full if mcp_compatible else True,
                limit=effective_limit,
                offset=offset,
            )

        if mcp_compatible:
            print_json(
                {
                    "status": "success",
                    "notebook_id": notebook_id,
                    "summary": {
                        "total": result["total"],
                        "completed": result["completed"],
                        "in_progress": result["in_progress"],
                        "queued": result["queued"],
                    },
                    "artifacts": result["artifacts"],
                    "pagination": {
                        "returned": result["returned"],
                        "offset": result["offset"],
                        "limit": result["limit"],
                        "has_more": result["has_more"],
                    },
                    "notebook_url": notebooks_service.notebook_url(client, notebook_id),
                }
            )
            return

        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_artifacts(result["artifacts"], full=full)
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("delete")
def studio_delete(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    artifact_id: str = typer.Argument(..., help="Artifact ID to delete"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Delete a studio artifact permanently."""
    notebook_id = get_alias_manager().resolve(notebook_id)
    artifact_id = get_alias_manager().resolve(artifact_id)

    if not confirm:
        typer.confirm(f"Are you sure you want to delete artifact {artifact_id}?", abort=True)

    try:
        with get_client(profile) as client:
            studio_service.delete_artifact(client, artifact_id, notebook_id)
        console.print(f"[green]✓[/green] Deleted artifact: {artifact_id}")
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("rename")
def studio_rename(
    artifact_id: str = typer.Argument(..., help="Artifact ID to rename"),
    new_title: str = typer.Argument(..., help="New title for the artifact"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Rename a studio artifact."""
    artifact_id = get_alias_manager().resolve(artifact_id)

    try:
        with get_client(profile) as client:
            result = studio_service.rename_artifact(client, artifact_id, new_title)
        console.print(f"[green]✓[/green] Renamed artifact to: {result['new_title']}")
    except (ValidationError, ServiceError) as e:
        handle_error(e)
    except NLMError as e:
        handle_error(e)


# ========== Audio ==========


@audio_app.command("create")
def create_audio(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    format: str = typer.Option(
        "deep_dive",
        "--format",
        "-f",
        help="Overview format (deep_dive, brief, critique, debate)",
    ),
    length: str = typer.Option(
        "default",
        "--length",
        "-l",
        help="Length (short, default, long)",
    ),
    language: str = typer.Option(
        "",
        "--language",
        help="BCP-47 language code (default: NOTEBOOKLM_HL or en)",
    ),
    focus: str | None = typer.Option(
        None,
        "--focus",
        help="Optional focus topic",
    ),
    source_ids: str | None = typer.Option(
        None,
        "--source-ids",
        "-s",
        help="Comma-separated source IDs",
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create an audio overview (podcast) from notebook sources."""
    if not confirm:
        typer.confirm(f"Create {format} audio overview?", abort=True)

    _run_create(
        notebook_id,
        "audio",
        "audio",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        audio_format=format,
        audio_length=length,
        language=language,
        focus_prompt=focus or "",
    )


# ========== Report ==========


@report_app.command("create")
def create_report(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    format: str = typer.Option(
        "Briefing Doc",
        "--format",
        "-f",
        help="Format: 'Briefing Doc', 'Study Guide', 'Blog Post', 'Create Your Own', 'Interactive'",
    ),
    template: str = typer.Option(
        "learning_overview",
        "--template",
        "-t",
        help="Interactive report template (only used with --format Interactive)",
    ),
    prompt: str = typer.Option(
        "", "--prompt", help="Custom prompt (required for 'Create Your Own')"
    ),
    language: str = typer.Option(
        "", "--language", help="BCP-47 language code (default: NOTEBOOKLM_HL or en)"
    ),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a report from notebook sources."""
    if format == "Create Your Own" and not prompt:
        console.print("[red]Error:[/red] --prompt is required when format is 'Create Your Own'")
        raise typer.Exit(1)

    if not confirm:
        typer.confirm(f"Create '{format}' report?", abort=True)

    _run_create(
        notebook_id,
        "report",
        "report",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        report_format=format,
        report_template=template,
        custom_prompt=prompt,
        language=language,
    )


def _resolve_notebook(notebook_id: str) -> str:
    """Resolve an alias/partial id to a full notebook UUID."""
    return str(get_alias_manager().resolve(notebook_id))


@report_app.command("get")
def get_report(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    artifact_id: str = typer.Argument(..., help="Interactive report artifact ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Write the markdown to a file instead of stdout"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Read an interactive report (markdown content + metadata)."""
    try:
        resolved = _resolve_notebook(notebook_id)
        with get_client(profile) as client:
            report = studio_service.get_report(client, resolved, artifact_id)

        if json_output:
            print_json(report)
            return

        markdown = report.get("markdown")
        if not markdown:
            console.print(
                "[yellow]Report has no generated content yet.[/yellow] "
                "Check 'nlm studio status' for progress."
            )
            raise typer.Exit(1)

        if output:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown, encoding="utf-8")
            console.print(f"[green]✓[/green] Wrote {len(markdown)} characters to {path}")
        else:
            typer.echo(markdown)
    except (ValidationError, ServiceError) as e:
        if json_output:
            handle_error(e, json_output=True)
        msg = e.user_message if isinstance(e, ServiceError) else str(e)
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1) from e
    except NLMError as e:
        handle_error(e, json_output=json_output)


MAX_PLAN_FILE_BYTES = 256 * 1024


def _parse_settings(pairs: list[str] | None) -> dict[str, str]:
    settings: dict[str, str] = {}
    for pair in pairs or []:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip() or not value.strip():
            console.print(f"[red]Error:[/red] --setting must be name=value (got '{pair}')")
            raise typer.Exit(1)
        settings[name.strip()] = value.strip()
    return settings


@report_app.command("elements")
def list_elements(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    artifact_id: str = typer.Argument(..., help="Interactive report artifact ID"),
    wait: list[str] | None = typer.Option(  # noqa: B008
        None, "--wait", help="Element id to wait on (repeatable)"
    ),
    timeout: int = typer.Option(600, "--timeout", help="Max seconds to wait"),
    content: bool = typer.Option(
        False, "--content", help="Include quiz/flashcards/mind map content"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List the embedded elements of an interactive report."""
    try:
        resolved = _resolve_notebook(notebook_id)
        with get_client(profile) as client:
            listing = studio_service.list_report_elements(
                client,
                resolved,
                artifact_id,
                wait_for=wait or None,
                timeout=float(timeout),
                include_content=content,
            )

        elements = listing["elements"]
        if json_output:
            print_json({**listing, "total": len(elements)})
            return

        if not elements:
            console.print("[yellow]No embedded elements in this report.[/yellow]")
            return

        for element in elements:
            title = (element.get("title") or "").strip() or "(untitled)"
            # Escape brackets so rich treats them as literal text, not markup.
            console.print(
                f"[bold]{element.get('type', 'unknown')}[/bold] "
                f"\\[{element.get('element_status', 'unknown')}] {title}"
            )
            console.print(f"  ID: {element.get('element_id', 'unknown')}")
            if element.get("description"):
                console.print(f"  [dim]{escape(element['description'])}[/dim]")

        if listing.get("timed_out"):
            console.print("[yellow]Timed out; statuses above are current, not final.[/yellow]")
        if content and listing.get("review_label"):
            console.print(f"[dim]{listing['review_label']}[/dim]")
    except (ValidationError, ServiceError) as e:
        if json_output:
            handle_error(e, json_output=True)
        msg = e.user_message if isinstance(e, ServiceError) else str(e)
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1) from e
    except NLMError as e:
        handle_error(e, json_output=json_output)


element_app = typer.Typer(
    help="Manage embedded elements of an interactive report",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
report_app.add_typer(element_app, name="element")


@element_app.command("create")
def create_element(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    artifact_id: str = typer.Argument(..., help="Interactive report artifact ID"),
    element_id: str | None = typer.Option(
        None, "--id", help="Element ID (from 'nlm report elements')"
    ),
    element_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Element type selector: audio, video, mind_map, quiz, flashcards, slide_deck, infographic",
    ),
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        help="Custom steering prompt (default: the element card's description)",
    ),
    language: str = typer.Option(
        "", "--language", help="BCP-47 language code (default: the report's language)"
    ),
    setting: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--setting",
        help="Element setting name=value (repeatable); see 'nlm report elements --json'",
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Generate one embedded element of an interactive report."""
    if not element_id and not element_type:
        console.print("[red]Error:[/red] Provide --id or --type to select an element")
        raise typer.Exit(1)

    settings = _parse_settings(setting)

    if not confirm:
        selector = element_id or f"first {element_type} element"
        typer.confirm(f"Generate {selector} in report {artifact_id}?", abort=True)

    try:
        resolved = _resolve_notebook(notebook_id)
        with get_client(profile) as client:
            result = studio_service.generate_report_element(
                client,
                resolved,
                artifact_id,
                element_id=element_id,
                element_type=element_type,
                steering_prompt=prompt,
                language=language or None,
                settings=settings,
            )

        if json_output:
            print_json(result)
            return

        console.print(f"[green]✓[/green] {result.get('message', 'Element generation started')}")
        console.print(f"  Outcome: {result.get('outcome', 'unknown')}")
        console.print(f"  Element ID: {result.get('element_id', 'unknown')}")
        console.print(f"  Title: {result.get('title') or '(untitled)'}")
        console.print(f"\n[dim]Run 'nlm studio status {resolved}' to check progress.[/dim]")
    except (ValidationError, ServiceError) as e:
        if json_output:
            handle_error(e, json_output=True)
        msg = e.user_message if isinstance(e, ServiceError) else str(e)
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1) from e
    except NLMError as e:
        handle_error(e, json_output=json_output)


@element_app.command("create-batch")
def create_elements_batch(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    artifact_id: str = typer.Argument(..., help="Interactive report artifact ID"),
    plan: Path = typer.Option(  # noqa: B008
        ..., "--plan", help='JSON file: [{"element_id", "steering_prompt"?, "settings"?}]'
    ),
    language: str = typer.Option(
        "", "--language", help="BCP-47 code (default: the report's language)"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Generate several report elements from one plan file (validated first)."""
    try:
        if not plan.is_file() or plan.stat().st_size > MAX_PLAN_FILE_BYTES:
            raise ValidationError(
                f"Plan file must exist and be at most {MAX_PLAN_FILE_BYTES} bytes."
            )
        try:
            raw = json.loads(plan.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValidationError(f"Plan file is not valid JSON: {e}") from e
        items = studio_service.parse_element_plan(raw)
        resolved = _resolve_notebook(notebook_id)
        with get_client(profile) as client:
            if not confirm:
                prepared = studio_service.prepare_element_plan(
                    client, resolved, artifact_id, items, language or None
                )
                for el in prepared.elements:
                    console.print(f"[bold]{el.type}[/bold] {el.title} {el.settings_named or ''}")
                    console.print(f"  [dim]{escape(el.prompt[:200])}[/dim]")
                typer.confirm(
                    f"Start {len(prepared.elements)} generation(s) in report {artifact_id}?",
                    abort=True,
                )
            batch = studio_service.generate_report_elements(
                client, resolved, artifact_id, items, language=language or None
            )
        if json_output:
            print_json(batch)
            return
        for r in batch["results"]:
            colour = {"started": "green", "failed": "red", "unknown": "yellow"}.get(
                r["outcome"], "dim"
            )
            console.print(
                f"[{colour}]{r['outcome']}[/{colour}] {r['title'] or r['element_id']}"
                + (f" — {escape(r['error'])}" if r.get("error") else "")
            )
        if batch["stopped_reason"]:
            console.print(f"[yellow]Stopped early: {batch['stopped_reason']}[/yellow]")
    except (ValidationError, ServiceError) as e:
        if json_output:
            handle_error(e, json_output=True)
        msg = e.user_message if isinstance(e, ServiceError) else str(e)
        console.print(f"[red]Error:[/red] {msg}")
        raise typer.Exit(1) from e
    except NLMError as e:
        handle_error(e, json_output=json_output)


# ========== Quiz ==========


@quiz_app.command("create")
def create_quiz(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    count: int = typer.Option(2, "--count", "-c", help="Number of questions"),
    difficulty: int = typer.Option(2, "--difficulty", "-d", help="Difficulty 1-5 (1=easy, 5=hard)"),
    focus: str | None = typer.Option(
        None, "--focus", "-f", help="Focus prompt to guide generation"
    ),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a quiz from notebook sources."""
    if not confirm:
        typer.confirm(f"Create quiz with {count} questions?", abort=True)

    # Quiz CLI sends raw int codes directly — bypass service string resolution
    try:
        notebook_id_resolved = get_alias_manager().resolve(notebook_id)
        if json_output:
            with get_client(profile) as client:
                result = client.create_quiz(
                    notebook_id_resolved,
                    question_count=count,
                    difficulty=difficulty,
                    source_ids=parse_source_ids(source_ids),
                    focus_prompt=focus or "",
                )
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                progress.add_task("Creating quiz...", total=None)
                with get_client(profile) as client:
                    result = client.create_quiz(
                        notebook_id_resolved,
                        question_count=count,
                        difficulty=difficulty,
                        source_ids=parse_source_ids(source_ids),
                        focus_prompt=focus or "",
                    )

        if not result or not result.get("artifact_id"):
            handle_error(
                ServiceError(
                    "NotebookLM rejected quiz creation (no artifact returned).",
                    user_message="NotebookLM rejected quiz creation (no artifact returned).",
                    hint="Try again later or create from NotebookLM UI for diagnosis.",
                ),
                json_output=json_output,
            )

        if json_output:
            get_formatter(detect_output_format(True), console).format_item(
                {
                    "artifact_type": "quiz",
                    "artifact_id": result["artifact_id"],
                    "status": result.get("status", "in_progress"),
                    "message": "Quiz generation started.",
                }
            )
        else:
            console.print("[green]✓[/green] Quiz generation started")
            console.print(f"  Artifact ID: {result.get('artifact_id', 'unknown')}")
            console.print(
                f"\n[dim]Run 'nlm studio status {notebook_id_resolved}' to check progress.[/dim]"
            )
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


# ========== Flashcards ==========


@flashcards_app.command("create")
def create_flashcards(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    difficulty: str = typer.Option(
        "medium", "--difficulty", "-d", help="Difficulty: easy, medium, hard"
    ),
    focus: str | None = typer.Option(
        None, "--focus", "-f", help="Focus prompt to guide generation"
    ),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create flashcards from notebook sources."""
    if not confirm:
        typer.confirm("Create flashcards?", abort=True)

    _run_create(
        notebook_id,
        "flashcards",
        "flashcards",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        difficulty=difficulty,
        focus_prompt=focus or "",
    )


# ========== Mind Map ==========


@mindmap_app.command("create")
def create_mindmap(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    title: str = typer.Option("Mind Map", "--title", "-t", help="Mind map title"),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a mind map from notebook sources."""
    if not confirm:
        typer.confirm("Create mind map?", abort=True)

    _run_create(
        notebook_id,
        "mind_map",
        "mind map",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        title=title,
    )


# Note: mindmap list removed - use 'studio status' which now includes mindmaps


# ========== Slides ==========


@slides_app.command("create")
def create_slides(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    format: str = typer.Option(
        "detailed_deck", "--format", "-f", help="Format: detailed_deck, presenter_slides"
    ),
    length: str = typer.Option("default", "--length", "-l", help="Length: short, default"),
    language: str = typer.Option(
        "", "--language", help="BCP-47 language code (default: NOTEBOOKLM_HL or en)"
    ),
    focus: str = typer.Option("", "--focus", help="Optional focus topic"),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a slide deck from notebook sources."""
    if not confirm:
        typer.confirm("Create slide deck?", abort=True)

    _run_create(
        notebook_id,
        "slide_deck",
        "slide deck",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        slide_format=format,
        slide_length=length,
        language=language,
        focus_prompt=focus,
    )


@slides_app.command("revise")
def revise_slides(
    artifact_id: str = typer.Argument(..., help="Artifact ID of the slide deck to revise"),
    slide: list[str] = typer.Option(  # noqa: B008
        ...,
        "--slide",
        help='Slide revision in format: SLIDE_NUM "instruction" (e.g., --slide 1 "Make title larger")',
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Revise individual slides in an existing slide deck.

    Creates a NEW slide deck with revisions applied. The original is not modified.

    Examples:
        nlm slides revise <artifact-id> --slide '1 Make the title larger' --confirm
        nlm slides revise <artifact-id> --slide '1 Make title larger' --slide '3 Remove the image' --confirm
    """
    artifact_id = get_alias_manager().resolve(artifact_id)

    # Parse --slide arguments: each is "NUMBER instruction text"
    instructions: list[dict] = []
    for s in slide:
        parts = s.strip().split(None, 1)
        if len(parts) < 2:
            console.print(
                f"[red]Error:[/red] Invalid --slide format: '{s}'. Expected: NUMBER \"instruction\""
            )
            raise typer.Exit(1)
        try:
            slide_num = int(parts[0])
        except ValueError:
            console.print(
                f"[red]Error:[/red] Invalid slide number: '{parts[0]}'. Must be an integer >= 1."
            )
            raise typer.Exit(1) from None
        instructions.append({"slide": slide_num, "instruction": parts[1]})

    if not confirm:
        console.print("[bold]Slides to revise:[/bold]")
        for inst in instructions:
            console.print(f"  Slide {inst['slide']}: {inst['instruction']}")
        console.print("\n[dim]This creates a NEW slide deck. The original is not modified.[/dim]")
        typer.confirm("Proceed with revision?", abort=True)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            progress.add_task("Revising slide deck...", total=None)
            with get_client(profile) as client:
                result = studio_service.revise_artifact(
                    client,
                    artifact_id,
                    instructions,
                )

        console.print("[green]✓[/green] Slide deck revision started")
        console.print(f"  New Artifact ID: {result.get('artifact_id', 'unknown')}")
        console.print(f"  Original: {artifact_id}")
        console.print("\n[dim]Run 'nlm studio status <notebook-id>' to check progress.[/dim]")
    except (ValidationError, ServiceError) as e:
        handle_error(e)
    except NLMError as e:
        handle_error(e)


# ========== Infographic ==========


@infographic_app.command("create")
def create_infographic(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    orientation: str = typer.Option(
        "landscape", "--orientation", "-o", help="Orientation: landscape, portrait, square"
    ),
    detail: str = typer.Option(
        "standard", "--detail", "-d", help="Detail level: concise, standard, detailed"
    ),
    style: str = typer.Option(
        "auto_select",
        "--style",
        help="Visual style: auto_select, sketch_note, professional, bento_grid, editorial, instructional, bricks, clay, anime, kawaii, scientific",
    ),
    language: str = typer.Option(
        "", "--language", help="BCP-47 language code (default: NOTEBOOKLM_HL or en)"
    ),
    focus: str = typer.Option("", "--focus", help="Optional focus topic"),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create an infographic from notebook sources."""
    if not confirm:
        typer.confirm("Create infographic?", abort=True)

    _run_create(
        notebook_id,
        "infographic",
        "infographic",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        orientation=orientation,
        detail_level=detail,
        infographic_style=style,
        language=language,
        focus_prompt=focus,
    )


# ========== Video ==========


@video_app.command("create")
def create_video(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    format: str = typer.Option(
        "explainer", "--format", "-f", help="Format: explainer, brief, cinematic, short"
    ),
    style: str = typer.Option(
        "auto_select",
        "--style",
        "-s",
        help="Visual style: auto_select, custom, classic, whiteboard, kawaii, anime, watercolor, retro_print, heritage, paper_craft",
    ),
    style_prompt: str = typer.Option(
        "",
        "--style-prompt",
        help="Custom visual style description. For explainer/brief: implies --style custom. For cinematic/short: mapped to --focus (custom_instructions).",
    ),
    language: str = typer.Option(
        "",
        "--language",
        help="BCP-47 language code. Short format uses best-effort prompt steering.",
    ),
    focus: str = typer.Option(
        "",
        "--focus",
        help="Focus topic or creative direction. For cinematic/short formats, this is the full steering prompt (visual style, audience, narrative).",
    ),
    source_ids: str | None = typer.Option(None, "--source-ids", help="Comma-separated source IDs"),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a video overview from notebook sources."""
    if not confirm:
        typer.confirm("Create video overview?", abort=True)

    _run_create(
        notebook_id,
        "video",
        "video",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        video_format=format,
        visual_style=style,
        video_style_prompt=style_prompt,
        language=language,
        focus_prompt=focus,
    )


@video_app.command("list")
def list_videos(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    full: bool = typer.Option(False, "--full", "-a", help="Show all details"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """List video artifacts and their status."""
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = studio_service.get_studio_status(client, notebook_id)

        videos = [artifact for artifact in result["artifacts"] if artifact.get("type") == "video"]
        fmt = detect_output_format(json_output)
        formatter = get_formatter(fmt, console)
        formatter.format_artifacts(videos, full=full)
    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


# ========== Data Table ==========


@data_table_app.command("create")
def create_data_table(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    description: str = typer.Argument(..., help="Description of the data table to create"),
    language: str = typer.Option(
        "", "--language", help="BCP-47 language code (default: NOTEBOOKLM_HL or en)"
    ),
    source_ids: str | None = typer.Option(
        None, "--source-ids", "-s", help="Comma-separated source IDs"
    ),
    confirm: bool = typer.Option(False, "--confirm", "-y", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """Create a data table from notebook sources."""
    if not confirm:
        typer.confirm("Create data table?", abort=True)

    _run_create(
        notebook_id,
        "data_table",
        "data table",
        profile=profile,
        json_output=json_output,
        source_ids=parse_source_ids(source_ids),
        description=description,
        language=language,
    )
