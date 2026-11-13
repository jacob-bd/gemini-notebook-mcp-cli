"""Chat configuration CLI commands."""

import typer

from notebooklm_tools.cli.utils import get_client, handle_error, make_console
from notebooklm_tools.services import ServiceError
from notebooklm_tools.services import chat as chat_service
from notebooklm_tools.services.aliases import get_alias_manager
from notebooklm_tools.services.errors import NLMError

console = make_console()
app = typer.Typer(
    help="Configure chat settings",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


@app.command("configure")
def configure_chat(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    goal: str = typer.Option(
        "default",
        "--goal",
        "-g",
        help="Chat goal: default, learning_guide, or custom",
    ),
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        help="Custom prompt (required when goal=custom, max 10000 chars)",
    ),
    response_length: str = typer.Option(
        "default",
        "--response-length",
        "-r",
        help="Response length: default, longer, or shorter",
    ),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """
    Configure how AI responds in notebook chat.

    Goals:
    - default: Standard helpful responses
    - learning_guide: Educational, step-by-step explanations
    - custom: Use your own prompt to guide the AI
    """
    try:
        notebook_id = get_alias_manager().resolve(notebook_id)
        with get_client(profile) as client:
            result = chat_service.configure_chat(
                client,
                notebook_id,
                goal=goal,
                custom_prompt=prompt,
                response_length=response_length,
            )

        console.print("[green]✓[/green] Chat configuration updated")
        console.print(f"  Goal: {result['goal']}")
        if prompt:
            preview = prompt[:50] + "..." if len(prompt) > 50 else prompt
            console.print(f"  Prompt: {preview}")
        console.print(f"  Response length: {result['response_length']}")

    except (ServiceError, NLMError) as e:
        handle_error(e, json_output=locals().get("json_output", False))


@app.command("start")
def start_chat(
    notebook_id: str = typer.Argument(..., help="Notebook ID"),
    profile: str | None = typer.Option(None, "--profile", "-p", help="Profile to use"),
) -> None:
    """
    Start interactive chat session with a notebook.

    Enter a REPL where you can have multi-turn conversations.
    Use /help for commands, /exit to quit.
    """
    from notebooklm_tools.cli.commands.repl import run_chat_repl

    run_chat_repl(notebook_id, profile)
