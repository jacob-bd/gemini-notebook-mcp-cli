"""Download CLI commands."""

import asyncio
from collections.abc import Callable
from typing import Any

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import downloads as downloads_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import ArtifactNotReadyError

app = typer.Typer(help="Download artifacts from notebooks.")
console = make_console()
err_console = make_console(stderr=True)


def _download_with_progress(
    download_func: Callable[[Callable[[int, int], None]], Any],
    description: str,
    show_progress: bool = True,
):
    """Wrapper to show progress bar for downloads (CLI-only presentation concern)."""
    if not show_progress:
        return download_func(lambda current, total: None)

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=None),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(description, total=None)

        def update_progress(current: int, total: int | None):
            if total:
                progress.update(task_id, completed=current, total=total)
            else:
                progress.update(task_id, completed=current)

        return download_func(update_progress)


def _streaming_download(
    notebook_id: str,
    artifact_type: str,
    output: str | None,
    artifact_id: str | None,
    no_progress: bool,
    default_suffix: str,
    description: str,
    slide_deck_format: str = "pdf",
) -> None:
    """Common pattern for streaming (async with progress) downloads."""
    notebook_id = get_alias_manager().resolve(notebook_id)
    downloads_service.validate_artifact_type(artifact_type)

    client = get_client()
    path = output or f"{notebook_id}_{default_suffix}"

    try:
        saved = _download_with_progress(
            lambda cb: asyncio.run(
                downloads_service.download_async(
                    client,
                    notebook_id,
                    artifact_type,
                    path,
                    artifact_id=artifact_id,
                    progress_callback=cb,
                    slide_deck_format=slide_deck_format,
                )
            )["path"],
            description,
            show_progress=not no_progress,
        )
        console.print(f"[green]✓[/green] Downloaded {artifact_type.replace('_', ' ')} to: {saved}")
    except ArtifactNotReadyError:
        err_console.print(
            f"[red]Error:[/red] {description.replace('Downloading ', '').title()} is not ready or does not exist."
        )
        raise typer.Exit(1) from None
    except ServiceError as e:
        err_console.print(f"[red]Error:[/red] {e.user_message}")
        raise typer.Exit(1) from e
    except Exception as e:
        handle_error(e)


def _simple_download(
    notebook_id: str,
    artifact_type: str,
    output: str | None,
    artifact_id: str | None,
    default_suffix: str,
    client: Any | None = None,
) -> None:
    """Common pattern for simple (synchronous) downloads."""
    notebook_id = get_alias_manager().resolve(notebook_id)
    downloads_service.validate_artifact_type(artifact_type)

    path = output or f"{notebook_id}_{default_suffix}"
    if client is None:
        client = get_client()

    try:
        result = downloads_service.download_sync(
            client,
            notebook_id,
            artifact_type,
            path,
            artifact_id=artifact_id,
        )
        console.print(
            f"[green]✓[/green] Downloaded {artifact_type.replace('_', ' ')} to: {result['path']}"
        )
    except ArtifactNotReadyError:
        err_console.print(
            f"[red]Error:[/red] {artifact_type.replace('_', ' ').title()} is not ready or does not exist."
        )
        raise typer.Exit(1) from None
    except ServiceError as e:
        err_console.print(f"[red]Error:[/red] {e.user_message}")
        raise typer.Exit(1) from e
    except Exception as e:
        handle_error(e)


def _interactive_download(
    notebook_id: str,
    artifact_type: str,
    output: str | None,
    artifact_id: str | None,
    output_format: str,
) -> None:
    """Common pattern for interactive artifact downloads (quiz/flashcards)."""
    notebook_id = get_alias_manager().resolve(notebook_id)
    downloads_service.validate_artifact_type(artifact_type)
    downloads_service.validate_output_format(output_format)

    ext = downloads_service.get_default_extension(artifact_type, output_format)
    path = output or f"{notebook_id}_{artifact_type}.{ext}"
    client = get_client()

    try:
        result_dict = asyncio.run(
            downloads_service.download_async(
                client,
                notebook_id,
                artifact_type,
                path,
                artifact_id=artifact_id,
                output_format=output_format,
            )
        )
        console.print(
            f"[green]✓[/green] Downloaded {artifact_type.replace('_', ' ')} to: {result_dict['path']}"
        )
    except ArtifactNotReadyError:
        err_console.print(
            f"[red]Error:[/red] {artifact_type.replace('_', ' ').title()} is not ready or does not exist."
        )
        raise typer.Exit(1) from None
    except ServiceError as e:
        err_console.print(f"[red]Error:[/red] {e.user_message}")
        raise typer.Exit(1) from e
    except ValueError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        handle_error(e)


# --- Bulk download ---


def _print_download_all_result(result: dict) -> None:
    """Human-readable output for a single-notebook download_all result."""
    console.print(f"Notebook: [bold]{result['notebook_title']}[/bold]")
    console.print(f"Directory: {result['output_dir']}")
    for item in result["items"]:
        label = item["artifact_type"].replace("_", " ")
        if item["success"]:
            console.print(f"[green]✓[/green] {label}: {item['path']}")
        else:
            console.print(f"[red]✗[/red] {label} ({item['title']}): {item['error']}")
    for skipped in result["skipped"]:
        if skipped["reason"] == "type not requested":
            continue
        label = skipped["artifact_type"].replace("_", " ")
        console.print(
            f"[yellow]-[/yellow] skipped {label} ({skipped['title']}): {skipped['reason']}"
        )
    if result["total_artifacts"] == 0:
        console.print("No studio artifacts found in this notebook.")
    console.print(
        f"\n[bold]{result['downloaded']}[/bold] downloaded, "
        f"{result['failed']} failed, {len(result['skipped'])} skipped"
    )


def _print_sweep_result(result: dict) -> None:
    """Human-readable output for an all-notebooks sweep result."""
    console.print(f"Directory: {result['output_dir']}")
    for nb in result["notebooks"]:
        if nb["error"]:
            console.print(f"[red]✗[/red] {nb['notebook_title']}: {nb['error']}")
        else:
            console.print(
                f"[green]✓[/green] {nb['notebook_title']}: "
                f"{nb['downloaded']} downloaded, {nb['failed']} failed, "
                f"{nb['skipped']} skipped"
            )
    console.print(
        f"\n[bold]{result['downloaded']}[/bold] downloaded, {result['failed']} failed "
        f"across {result['total_notebooks']} notebooks "
        f"({result['errored_notebooks']} notebooks errored)"
    )


@app.command("all")
def download_all_cmd(
    notebook_id: str | None = typer.Argument(
        None, help="Notebook ID or alias (omit with --all-notebooks)"
    ),
    output_dir: str = typer.Option(
        ".",
        "--output-dir",
        "-d",
        help="Base directory; a subdirectory named after each notebook is created inside",
    ),
    types: str | None = typer.Option(
        None,
        "--types",
        "-t",
        help="Comma-separated artifact types (default: all). Example: video,slide_deck,mind_map,report",
    ),
    slide_format: str = typer.Option(
        "pdf", "--slide-format", help="Slide deck format: pdf (default) or pptx"
    ),
    interactive_format: str = typer.Option(
        "json", "--interactive-format", help="Quiz/flashcards format: json, markdown, or html"
    ),
    all_notebooks: bool = typer.Option(
        False, "--all-notebooks", "-a", help="Sweep every notebook in the account"
    ),
    skip_existing: bool = typer.Option(
        False,
        "--skip-existing",
        help="Skip artifacts whose file already exists (incremental re-runs)",
    ),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable download progress bars"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output result as JSON"),
):
    """Download all completed artifacts into per-notebook directories.

    With a notebook ID, downloads that notebook's artifacts. With
    --all-notebooks, sweeps every notebook in the account.
    """
    if all_notebooks == (notebook_id is not None):
        err_console.print(
            "[red]Error:[/red] Provide either a notebook ID or --all-notebooks (not both)."
        )
        raise typer.Exit(1)

    artifact_types = [t.strip() for t in types.split(",") if t.strip()] if types else None
    client = get_client()

    def _run(
        progress_factory: Callable[[str, str], Callable[[int, int], None]] | None,
        on_notebook: Callable[[int, int, str], None] | None,
    ) -> dict:
        common = {
            "artifact_types": artifact_types,
            "output_format": interactive_format,
            "slide_deck_format": slide_format.lower(),
            "skip_existing": skip_existing,
            "progress_factory": progress_factory,
        }
        if all_notebooks:
            return asyncio.run(
                downloads_service.download_all_notebooks(
                    client, output_dir, on_notebook=on_notebook, **common
                )
            )
        resolved = get_alias_manager().resolve(notebook_id)
        return asyncio.run(downloads_service.download_all(client, resolved, output_dir, **common))

    try:
        if no_progress or json_output:
            result = _run(None, None)
        else:
            with Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.0f}%",
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
                console=console,
                transient=True,
            ) as progress:

                def _progress_factory(
                    artifact_type: str, filename: str
                ) -> Callable[[int, int], None]:
                    task_id = progress.add_task(f"Downloading {filename}", total=None)

                    def update_progress(current: int, total: int | None):
                        if total:
                            progress.update(task_id, completed=current, total=total)
                        else:
                            progress.update(task_id, completed=current)

                    return update_progress

                def _on_notebook(index: int, total: int, title: str) -> None:
                    progress.console.print(f"[dim][{index}/{total}][/dim] {title}")

                result = _run(_progress_factory, _on_notebook)
    except ServiceError as e:
        err_console.print(f"[red]Error:[/red] {e.user_message}")
        raise typer.Exit(1) from e
    except Exception as e:
        handle_error(e)
        return

    if json_output:
        console.print_json(data=result)
    elif all_notebooks:
        _print_sweep_result(result)
    else:
        _print_download_all_result(result)

    if result["downloaded"] == 0 and (
        result["failed"] > 0 or result.get("errored_notebooks", 0) > 0
    ):
        raise typer.Exit(1)


# --- Streaming downloads (with progress bars) ---


@app.command("audio")
def download_audio(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_audio.m4a)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable download progress bar"),
):
    """Download Audio Overview."""
    _streaming_download(
        notebook_id, "audio", output, artifact_id, no_progress, "audio.m4a", "Downloading audio"
    )


@app.command("video")
def download_video(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_video.mp4)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable download progress bar"),
):
    """Download Video Overview."""
    _streaming_download(
        notebook_id, "video", output, artifact_id, no_progress, "video.mp4", "Downloading video"
    )


@app.command("slide-deck")
def download_slide_deck(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_slides.{ext})"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable download progress bar"),
    format: str = typer.Option("pdf", "--format", "-f", help="File format: pdf (default) or pptx"),
):
    """Download Slide Deck (PDF or PPTX)."""
    fmt = format.lower()
    if fmt not in ("pdf", "pptx"):
        err_console.print("[red]Error:[/red] --format must be 'pdf' or 'pptx'")
        raise typer.Exit(1)
    default_suffix = f"slides.{fmt}"
    _streaming_download(
        notebook_id,
        "slide_deck",
        output,
        artifact_id,
        no_progress,
        default_suffix,
        "Downloading slide deck",
        slide_deck_format=fmt,
    )


@app.command("infographic")
def download_infographic(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_infographic.png)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
    no_progress: bool = typer.Option(False, "--no-progress", help="Disable download progress bar"),
):
    """Download Infographic (PNG)."""
    _streaming_download(
        notebook_id,
        "infographic",
        output,
        artifact_id,
        no_progress,
        "infographic.png",
        "Downloading infographic",
    )


# --- Simple (synchronous) downloads ---


@app.command("report")
def download_report(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_report.md)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
):
    """Download Report (Markdown)."""
    _simple_download(notebook_id, "report", output, artifact_id, "report.md")


@app.command("mind-map")
def download_mind_map(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_mindmap.json)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID (note ID)"),
):
    """Download Mind Map (JSON)."""
    _simple_download(notebook_id, "mind_map", output, artifact_id, "mindmap.json")


@app.command("data-table")
def download_data_table(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_table.csv)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
):
    """Download Data Table (CSV or XLSX)."""
    if output is not None:
        _simple_download(notebook_id, "data_table", output, artifact_id, "table.csv")
        return

    # The legacy command accepts both CSV (type 9) and XLSX (type 10)
    # artifacts. Inspect the selected artifact before choosing the default
    # filename so an XLSX payload is not misleadingly saved as .csv.
    client = get_client()
    default_suffix = "table.csv"
    try:
        status = downloads_service.get_studio_status(
            client, get_alias_manager().resolve(notebook_id), include_details=False
        )
        candidates = [
            artifact
            for artifact in status["artifacts"]
            if artifact.get("status") == "completed"
            and artifact.get("type") in ("data_table", "data_table_xlsx")
        ]
        target = (
            next(
                (artifact for artifact in candidates if artifact.get("artifact_id") == artifact_id),
                None,
            )
            if artifact_id
            else (candidates[0] if candidates else None)
        )
        if target and target.get("type") == "data_table_xlsx":
            default_suffix = "table.xlsx"
    except ServiceError:
        # Let the actual download perform its normal readiness/error handling.
        pass

    _simple_download(
        notebook_id,
        "data_table",
        output,
        artifact_id,
        default_suffix,
        client=client,
    )


@app.command("file")
def download_file(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_file.bin)"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
):
    """Download a generic Studio file export."""
    _simple_download(notebook_id, "file", output, artifact_id, "file.bin")


# --- Interactive format downloads (quiz/flashcards) ---


@app.command("quiz")
def download_quiz_cmd(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_quiz.{ext})"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
    format: str = typer.Option(
        "json", "--format", "-f", help="Output format: json, markdown, or html"
    ),
):
    """Download Quiz."""
    _interactive_download(notebook_id, "quiz", output, artifact_id, format)


@app.command("flashcards")
def download_flashcards_cmd(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    output: str | None = typer.Option(
        None, "--output", "-o", help="Output path (default: ./{notebook_id}_flashcards.{ext})"
    ),
    artifact_id: str | None = typer.Option(None, "--id", help="Specific artifact ID"),
    format: str = typer.Option(
        "json", "--format", "-f", help="Output format: json, markdown, or html"
    ),
):
    """Download Flashcards."""
    _interactive_download(notebook_id, "flashcards", output, artifact_id, format)
