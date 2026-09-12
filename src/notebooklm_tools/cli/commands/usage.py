"""Show how much of the plan's usage allowance is left."""

import json as json_lib
from datetime import UTC, datetime

import typer
from rich.table import Table

from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import usage as usage_service

console = make_console()
app = typer.Typer(
    name="usage",
    help="Show remaining plan usage and reset times",
    invoke_without_command=True,
)

_WINDOW_LABELS = {
    "rolling": "Rolling window",
    "weekly": "Weekly limit",
}


def _format_reset(iso_value: str | None) -> str:
    """Render a reset time in the user's local timezone."""
    if not iso_value:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError:
        return iso_value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _format_percent(value: float | None) -> str:
    """Render a percentage, distinguishing unknown from zero."""
    if value is None:
        return "unknown"
    return f"{value:.1f}%"


@app.callback(invoke_without_command=True)
def usage(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """
    Show how much of your plan's usage allowance is left.

    Gemini Notebook meters usage as compute against two windows at once: a short
    rolling window and a weekly one. Both are shown with their reset times.

    Examples:
        nlm usage
        nlm usage --json
    """
    if ctx.invoked_subcommand is not None:
        return

    try:
        client = get_client()
        result = usage_service.get_usage(client)
    except Exception as e:
        handle_error(e, json_output)
        return

    if json_output:
        console.print(json_lib.dumps(result, indent=2))
        return

    table = Table(title="Gemini Notebook usage")
    table.add_column("Window", style="cyan")
    table.add_column("Used", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Resets")

    for window in result["windows"]:
        table.add_row(
            _WINDOW_LABELS.get(window["window"], window["window"]),
            _format_percent(window["percent_used"]),
            _format_percent(window["percent_remaining"]),
            _format_reset(window["resets_at"]),
        )

    console.print(table)

    tier = result.get("tier")
    console.print(f"Plan: [bold]{tier}[/bold]" if tier else "Plan: [dim]unknown[/dim]")
