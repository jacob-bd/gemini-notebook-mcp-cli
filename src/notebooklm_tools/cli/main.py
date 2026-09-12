"""Main CLI application for NotebookLM Tools."""

import contextlib
import logging
from typing import Any

import typer

from notebooklm_tools import __version__
from notebooklm_tools.cli.commands.alias import app as alias_app
from notebooklm_tools.cli.commands.batch import app as batch_app
from notebooklm_tools.cli.commands.chat import app as chat_app
from notebooklm_tools.cli.commands.chats import chats_app
from notebooklm_tools.cli.commands.config import app as config_app
from notebooklm_tools.cli.commands.cross import app as cross_app
from notebooklm_tools.cli.commands.doctor import app as doctor_app
from notebooklm_tools.cli.commands.download import app as download_app
from notebooklm_tools.cli.commands.export import app as export_app
from notebooklm_tools.cli.commands.label import app as label_app
from notebooklm_tools.cli.commands.note import app as note_app
from notebooklm_tools.cli.commands.notebook import app as notebook_app
from notebooklm_tools.cli.commands.pipeline import app as pipeline_app
from notebooklm_tools.cli.commands.research import app as research_app
from notebooklm_tools.cli.commands.setup import app as setup_app
from notebooklm_tools.cli.commands.share import app as share_app
from notebooklm_tools.cli.commands.skill import app as skill_app
from notebooklm_tools.cli.commands.source import app as source_app
from notebooklm_tools.cli.commands.studio import (
    app as studio_app,
)
from notebooklm_tools.cli.commands.studio import (
    audio_app,
    data_table_app,
    flashcards_app,
    infographic_app,
    mindmap_app,
    quiz_app,
    report_app,
    slides_app,
    video_app,
)
from notebooklm_tools.cli.commands.tag import app as tag_app
from notebooklm_tools.cli.commands.usage import app as usage_app
from notebooklm_tools.cli.commands.verbs import (
    add_app,
    configure_app,
    content_app,
    create_app,
    delete_app,
    describe_app,
    get_app,
    install_app,
    list_app,
    query_app,
    rename_app,
    set_app,
    show_app,
    stale_app,
    status_app,
    sync_app,
    uninstall_app,
    update_app,
)
from notebooklm_tools.cli.utils import make_console

console = make_console()

# Main application
app = typer.Typer(
    name="nlm",
    help="NotebookLM Tools - Unified CLI for Google NotebookLM",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# =============================================================================
# LOGIN app with nested profile commands
# =============================================================================

login_app = typer.Typer(
    help="Authentication and profile management",
    rich_markup_mode="rich",
)

# Profile management subcommands
profile_app = typer.Typer(
    help="Manage authentication profiles",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

# Non-interactive session maintenance (for unattended installs / schedulers)
auth_app = typer.Typer(
    help="Session auth maintenance (headless refresh for schedulers)",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


def _auth_failure_from_result(result: Any) -> Exception:
    """Translate a failed AuthCheckResult into a CLI-facing AuthenticationError.

    Args:
        result: An AuthCheckResult with ``valid=False``.

    Returns:
        An AuthenticationError whose message/hint match the failure reason.
    """
    from notebooklm_tools.core.exceptions import AuthenticationError

    reason = result.reason or "unknown"
    if reason == "no_tokens":
        return AuthenticationError(
            "No saved credentials found.",
            hint="Run 'nlm login' to authenticate.",
        )
    if reason == "expired":
        return AuthenticationError(
            "Credentials have expired.",
            hint="Run 'nlm login' to re-authenticate.",
        )
    if reason.startswith("network_error"):
        return AuthenticationError(
            f"Could not reach NotebookLM ({reason}).",
            hint="Check your connection and try again — your saved credentials may still be valid.",
        )
    return AuthenticationError(
        f"Authentication check failed ({reason}).",
        hint="Run 'nlm login' to re-authenticate.",
    )


def _best_effort_notebook_count(profile: Any) -> int | None:
    """Return the notebook count, or None if it cannot be retrieved quickly.

    The notebook count is a convenience shown alongside a successful auth
    check. A slow or timed-out notebook list must never turn an otherwise-valid
    session into a failure, so every error here degrades to ``None``.

    Args:
        profile: The loaded profile whose credentials are used for the call.

    Returns:
        The number of notebooks, or None if the list could not be fetched.
    """
    from notebooklm_tools.core.client import NotebookLMClient

    try:
        with NotebookLMClient(
            cookies=profile.cookies,
            csrf_token=profile.csrf_token or "",
            session_id=profile.session_id or "",
            build_label=profile.build_label or "",
            base_host=profile.base_host or "",
            profile_name=getattr(profile, "name", None),
        ) as client:
            return len(client.list_notebooks())
    except Exception:
        return None


def _validate_saved_profile(auth: Any) -> tuple[Any, int | None]:
    """Validate saved credentials using the lightweight authoritative check.

    Validity is decided by ``check_validity`` (a homepage probe), not by a full
    ``list_notebooks()`` call, so a slow notebook list on a large account cannot
    turn a valid session into a crash or false failure. The notebook count is
    fetched as a best-effort extra and is None when it cannot be retrieved.

    Args:
        auth: The AuthManager for the profile being checked.

    Returns:
        A tuple of (profile, notebook_count) where notebook_count may be None.

    Raises:
        AuthenticationError: If the credentials are not valid.
    """
    p = auth.load_profile()

    result = auth.check_validity(live=True)
    if not result.valid:
        raise _auth_failure_from_result(result)

    return p, _best_effort_notebook_count(p)


def _print_auth_valid(profile: Any, notebook_count: int | None) -> None:
    console.print("[green]✓[/green] Authentication valid!")
    console.print(f"  Profile: {profile.name}")
    if notebook_count is not None:
        console.print(f"  Notebooks found: {notebook_count}")
    else:
        console.print(
            "  [dim]Notebook count unavailable (network slow); credentials are valid[/dim]"
        )
    if profile.email:
        console.print(f"  Account: {profile.email}")


@login_app.callback(invoke_without_command=True)
def login_callback(
    ctx: typer.Context,
    manual: bool = typer.Option(
        False,
        "--manual",
        "-m",
        help="Manually provide cookies from a file",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Only check if current auth is valid",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile name (uses config default if not specified)",
    ),
    cookie_file: str | None = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to file containing cookies (for manual mode)",
    ),
    provider: str = typer.Option(
        "builtin",
        "--provider",
        help="Auth provider: builtin (default) or openclaw",
    ),
    cdp_url: str = typer.Option(
        "http://127.0.0.1:18800",
        "--cdp-url",
        help="CDP endpoint URL for external provider mode",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Force overwrite even if profile has credentials for a different account",
    ),
    clear: bool = typer.Option(
        False,
        "--clear",
        help="Delete the localized browser profile data before logging in, to switch Google accounts",
    ),
    wsl: bool = typer.Option(
        False,
        "--wsl",
        help="Launch Windows Chrome from WSL (fixes terminal corruption on WSL2)",
    ),
) -> None:
    """
    Authenticate with NotebookLM.

    Default: Uses the configured managed browser to extract cookies automatically.
    Use --manual to import cookies from a file.
    Use --check to validate existing credentials.
    Use --provider openclaw --cdp-url <url> to read auth from an existing
    OpenClaw-managed browser CDP endpoint.
    Use --wsl on WSL2 to launch Windows Chrome and avoid terminal corruption.

    To switch active accounts, run `nlm login switch <profile>`.
    """
    from notebooklm_tools.core.errors import ClientAuthenticationError
    from notebooklm_tools.core.exceptions import AccountMismatchError, NLMError
    from notebooklm_tools.services.auth import AuthManager
    from notebooklm_tools.utils.auth_browser import extract_cookies_via_browser, select_auth_backend
    from notebooklm_tools.utils.config import get_config

    # If a subcommand is invoked, don't run login logic
    if ctx.invoked_subcommand is not None:
        return

    # Use config default if no profile specified
    if profile is None:
        profile = get_config().auth.default_profile

    auth = AuthManager(profile)

    # Show which profile is being authenticated
    if not check and ctx.invoked_subcommand is None:
        try:
            existing = auth.load_profile()
            console.print(f"[dim]Authenticating profile: {profile} ({existing.email})[/dim]")
        except Exception:
            console.print(f"[dim]Authenticating profile: {profile}[/dim]")

    if check:
        # Check existing auth by making a real API call
        try:
            p, notebook_count = _validate_saved_profile(auth)
            console.print(f"[dim]Checking credentials for profile: {p.name}...[/dim]")
            _print_auth_valid(p, notebook_count)
        except NLMError as e:
            console.print(f"[red]✗[/red] Authentication failed: {e.message}")
            if e.hint:
                console.print(f"[dim]{e.hint}[/dim]")
            raise typer.Exit(2) from e
        return

    if manual:
        # Manual mode - read from file
        if not cookie_file:
            cookie_file = typer.prompt(
                "Enter path to file containing cookies",
                default="~/.nlm/cookies.txt",
            )
        try:
            auth.login_with_file(cookie_file)
            console.print("[green]✓[/green] Successfully authenticated!")
            console.print(f"  Profile saved: {profile}")
            console.print(f"  Credentials saved to: {auth.profile_dir}")
        except NLMError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            if e.hint:
                console.print(f"\n[dim]Hint: {e.hint}[/dim]")
            raise typer.Exit(1) from e
        return

    provider = (provider or "builtin").strip().lower()
    if provider not in {"builtin", "openclaw"}:
        console.print(f"[red]Error:[/red] Unsupported provider '{provider}'")
        console.print("[dim]Supported values: builtin, openclaw[/dim]")
        raise typer.Exit(1)

    if not force:
        try:
            p, notebook_count = _validate_saved_profile(auth)
            _print_auth_valid(p, notebook_count)
            return
        except (NLMError, ClientAuthenticationError):
            pass

    try:
        from notebooklm_tools.utils.cdp import (
            extract_cookies_via_cdp,
            extract_cookies_via_existing_cdp,
            terminate_chrome,
        )

        launched_local_chrome = False
        managed_browser_backend = ""
        managed_browser_name = ""

        # Default cdp_url for the builtin provider — used to detect when the
        # user explicitly passes their own --cdp-url value.
        _BUILTIN_CDP_DEFAULT = "http://127.0.0.1:18800"

        if wsl:
            # WSL mode: Launch Windows Chrome from WSL to avoid terminal corruption
            from notebooklm_tools.utils.wsl import (
                MIRRORED_LOOPBACK_IP,
                check_firewall_rule,
                get_windows_host_ip,
                is_wsl,
                launch_windows_chrome,
                terminate_windows_chrome,
                wait_for_cdp,
            )

            if not is_wsl():
                console.print(
                    "[yellow]Warning:[/yellow] --wsl flag used but not in WSL environment. Ignoring."
                )
                wsl = False

        if wsl:
            from notebooklm_tools.utils.wsl import DEFAULT_WSL_CDP_PORT, WSL_ADAPTER_ALIAS

            wsl_port = DEFAULT_WSL_CDP_PORT
            # Chrome binds to localhost only (newer Chrome ignores
            # --remote-debugging-address=0.0.0.0), so we launch it
            # on a different port and rely on a netsh portproxy rule
            # (listenport=wsl_port -> connectport=chrome_port) to
            # bridge WSL traffic to localhost.
            chrome_port = wsl_port + 1
            windows_ip = get_windows_host_ip()

            if not windows_ip:
                console.print("[red]Error:[/red] Could not determine Windows host IP.")
                console.print("[dim]Hint: Check /etc/resolv.conf in WSL[/dim]")
                raise typer.Exit(1)

            is_mirrored = windows_ip == MIRRORED_LOOPBACK_IP
            wsl_cdp_url = f"http://{windows_ip}:{wsl_port}"

            console.print("[bold]WSL2 detected - launching Windows Chrome[/bold]")
            console.print(
                f"[dim]Windows host: {windows_ip}:{wsl_port} (proxy) -> localhost:{chrome_port} (Chrome)[/dim]"
            )
            console.print("[dim]Chrome binds to localhost; netsh portproxy bridges WSL[/dim]")

            # Check Windows Firewall (not needed in mirrored mode —
            # loopback traffic never crosses the Windows Firewall)
            if is_mirrored:
                console.print(
                    "[dim]Mirrored networking: firewall rule not required (loopback)[/dim]"
                )
            elif not check_firewall_rule(wsl_port):
                console.print("\n[yellow]Windows Firewall Setup Required[/yellow]")
                console.print(
                    f"\nA firewall rule is needed to allow WSL to connect to Windows Chrome on port {wsl_port}."
                )
                console.print(
                    "\n[bold]Step 1:[/bold] Open [cyan]Windows PowerShell as Administrator[/cyan] and run:"
                )
                console.print(
                    f'\n  New-NetFirewallRule -DisplayName "NotebookLM-CDP-{wsl_port}" -Direction Inbound -Action Allow -Protocol TCP -LocalPort {wsl_port} -InterfaceAlias "{WSL_ADAPTER_ALIAS}" -RemoteAddress LocalSubnet\n'
                )
                console.print(
                    "[bold]Step 2:[/bold] After running the command above, press [bold]Enter[/bold] here to continue..."
                )

                input()

                # Re-check if rule was created
                if check_firewall_rule(wsl_port):
                    console.print("[green]✓[/green] Firewall rule detected!")
                else:
                    console.print(
                        "[yellow]Warning:[/yellow] Rule not yet detected, but will attempt to continue..."
                    )
                console.print()
            else:
                console.print("[dim]Windows Firewall: rule exists[/dim]")
                console.print(
                    f'[dim]If you created it before v0.11.2 it may not be scoped to "{WSL_ADAPTER_ALIAS}".[/dim]'
                )
                console.print(
                    "[dim]See docs/WSL_SETUP.md (Removing the bridge) to check and replace it.[/dim]"
                )
            console.print()

            try:
                chrome_process = launch_windows_chrome(chrome_port)
                console.print(f"[dim]Chrome PID: {chrome_process.pid}[/dim]")
            except RuntimeError as e:
                console.print(f"[red]Error:[/red] {e}")
                console.print("[dim]Hint: Ensure Chrome is installed on Windows side[/dim]")
                raise typer.Exit(1) from e

            console.print("[dim]Waiting for Chrome DevTools Protocol...[/dim]")
            if not wait_for_cdp(wsl_cdp_url, timeout=30):
                console.print(
                    f"[red]Error:[/red] Could not connect to CDP at {wsl_cdp_url} within 30 seconds."
                )
                console.print("\n[yellow]Troubleshooting:[/yellow]")
                if is_mirrored:
                    console.print(
                        "  1. Ensure the netsh portproxy rule is active (netsh interface portproxy show all)"
                    )
                else:
                    console.print("  1. Ensure the Windows Firewall rule was created (step above)")
                console.print("  2. If Chrome is still running, close it and retry")
                console.print("  3. Or use manual mode: nlm login --manual --file <path>")
                terminate_windows_chrome(chrome_process)
                raise typer.Exit(1)

            console.print("[green]✓[/green] Chrome ready, connecting...\n")

            try:
                result = extract_cookies_via_existing_cdp(
                    cdp_url=wsl_cdp_url,
                    wait_for_login=True,
                    login_timeout=300,
                )
            finally:
                # Always terminate Windows Chrome
                terminate_windows_chrome(chrome_process)

            launched_local_chrome = True

        elif provider == "openclaw" or (provider == "builtin" and cdp_url != _BUILTIN_CDP_DEFAULT):
            # External CDP path: connect to an already-running browser.
            # Triggered by --provider openclaw OR when the user explicitly
            # passes a --cdp-url (indicating they have a running Chrome).
            label = "openclaw" if provider == "openclaw" else "builtin (external CDP)"
            console.print("[bold]Using external CDP authentication[/bold]")
            console.print(f"[dim]Provider: {label} | CDP: {cdp_url}[/dim]\n")

            result = extract_cookies_via_existing_cdp(
                cdp_url=cdp_url,
                wait_for_login=True,
                login_timeout=300,
            )
        else:
            backend = select_auth_backend()
            if backend is None:
                extract_cookies_via_browser(profile_name=profile, clear_profile=clear)
                raise AssertionError("Authentication backend unexpectedly returned no result")

            managed_browser_backend = backend["backend"]
            managed_browser_name = backend["browser"]
            if managed_browser_backend == "firefox_profile":
                console.print("[bold]Launching Firefox for authentication...[/bold]")
                console.print("[dim]Using an isolated Firefox profile[/dim]\n")
                result, _ = extract_cookies_via_browser(
                    profile_name=profile,
                    clear_profile=clear,
                    preferred="firefox",
                )
            else:
                from notebooklm_tools.utils.cdp import get_chrome_path
                from notebooklm_tools.utils.config import (
                    check_migration_sources,
                    get_storage_dir,
                    run_migration,
                )

                get_chrome_path()
                console.print(
                    f"[bold]Launching {managed_browser_name} for authentication...[/bold]"
                )
                console.print("[dim]Using Chrome DevTools Protocol[/dim]\n")

                chrome_profile = get_storage_dir() / "chrome-profile"
                profile_exists = chrome_profile.exists() and (
                    (chrome_profile / "Default").exists()
                    or (chrome_profile / "Local State").exists()
                )
                if not profile_exists and not clear:
                    sources = check_migration_sources()
                    if sources["chrome_profiles"]:
                        console.print(
                            "[yellow]Found Chrome profile from legacy installation![/yellow]"
                        )
                        for src in sources["chrome_profiles"]:
                            console.print(f"  [dim]{src}[/dim]")
                        console.print("[dim]Migrating to new location...[/dim]")
                        for action in run_migration(dry_run=False):
                            console.print(f"  [green]✓[/green] {action}")
                        console.print()

                console.print(f"Starting {managed_browser_name}...")
                result = extract_cookies_via_cdp(
                    auto_launch=True,
                    wait_for_login=True,
                    login_timeout=300,
                    profile_name=profile,
                    clear_profile=clear,
                )
                launched_local_chrome = True

        if result.get("reused_existing"):
            console.print(
                f"[yellow]Warning:[/yellow] Connected to an already-running {managed_browser_name} instance. "
                "Profile isolation may not apply — verify the account is correct."
            )

        cookies = result["cookies"]
        csrf_token = result.get("csrf_token", "")
        session_id = result.get("session_id", "")
        email = result.get("email", "")
        build_label = result.get("build_label", "")
        base_host = result.get("base_host", "")

        # Save to profile
        auth.save_profile(
            cookies=cookies,
            csrf_token=csrf_token,
            session_id=session_id,
            email=email,
            force=force,
            build_label=build_label,
            base_host=base_host,
            browser_backend=managed_browser_backend or None,
        )

        # Close builtin auth Chrome to release profile lock (enables headless auth later)
        if launched_local_chrome:
            console.print(f"[dim]Closing {managed_browser_name}...[/dim]")
            terminate_chrome()

        console.print("\n[green]✓[/green] Successfully authenticated!")
        console.print(f"  Profile: {profile}")
        console.print(f"  Provider: {provider}")
        console.print(f"  Cookies: {len(cookies)} extracted")
        console.print(f"  CSRF Token: {'Yes' if csrf_token else 'No (will be auto-extracted)'}")
        if email:
            console.print(f"  Account: {email}")
        console.print(f"  Credentials saved to: {auth.profile_dir}")

    except AccountMismatchError as e:
        if provider == "builtin" and not force:
            # The Chrome data dir has a stale Google login from a different
            # account.  Auto-retry: clear it and relaunch so the user can
            # log in with the correct account.
            console.print(
                f"\n[yellow]⚠[/yellow]  Wrong Google account detected "
                f"([bold]{result.get('email', '?')}[/bold] instead of "
                f"[bold]{e.stored_email}[/bold])."
            )
            console.print(
                f"[dim]Clearing stale browser session and relaunching {managed_browser_name}...[/dim]\n"
            )

            if launched_local_chrome:
                with contextlib.suppress(Exception):
                    terminate_chrome()

            # Retry with cleared Chrome profile
            try:
                if managed_browser_backend == "firefox_profile":
                    result, _ = extract_cookies_via_browser(
                        profile_name=profile,
                        clear_profile=True,
                        preferred="firefox",
                    )
                else:
                    result = extract_cookies_via_cdp(
                        auto_launch=True,
                        wait_for_login=True,
                        login_timeout=300,
                        profile_name=profile,
                        clear_profile=True,
                    )
                    launched_local_chrome = True

                cookies = result["cookies"]
                csrf_token = result.get("csrf_token", "")
                session_id = result.get("session_id", "")
                email = result.get("email", "")
                build_label = result.get("build_label", "")
                base_host = result.get("base_host", "")

                auth.save_profile(
                    cookies=cookies,
                    csrf_token=csrf_token,
                    session_id=session_id,
                    email=email,
                    force=True,  # Allow overwrite on retry
                    build_label=build_label,
                    base_host=base_host,
                    browser_backend=managed_browser_backend or None,
                )

                if launched_local_chrome:
                    console.print(f"[dim]Closing {managed_browser_name}...[/dim]")
                    terminate_chrome()

                console.print("\n[green]✓[/green] Successfully authenticated!")
                console.print(f"  Profile: {profile}")
                console.print(f"  Provider: {provider}")
                console.print(f"  Cookies: {len(cookies)} extracted")
                console.print(
                    f"  CSRF Token: {'Yes' if csrf_token else 'No (will be auto-extracted)'}"
                )
                if email:
                    console.print(f"  Account: {email}")
                console.print(f"  Credentials saved to: {auth.profile_dir}")
            except NLMError as retry_err:
                console.print(f"\n[red]Error on retry:[/red] {retry_err.message}")
                if retry_err.hint:
                    console.print(f"\n[dim]Hint: {retry_err.hint}[/dim]")
                raise typer.Exit(1) from retry_err
        else:
            console.print(f"\n[red]Error:[/red] {e.message}")
            console.print(f"\n[yellow]Hint:[/yellow] {e.hint}")
            raise typer.Exit(1) from e
    except NLMError as e:
        console.print(f"\n[red]Error:[/red] {e.message}")
        if e.hint:
            console.print(f"\n[dim]Hint: {e.hint}[/dim]")
        raise typer.Exit(1) from e


@profile_app.command("list")
def profile_list() -> None:
    """List all authentication profiles."""
    from notebooklm_tools.services.auth import AuthManager

    profiles = AuthManager.list_profiles()

    if not profiles:
        console.print("[dim]No profiles found.[/dim]")
        console.print("\nRun 'nlm login' to create a profile.")
        return

    console.print("[bold]Available profiles:[/bold]")
    for name in profiles:
        try:
            auth = AuthManager(name)
            p = auth.load_profile()
            email = p.email or "Unknown"
            console.print(f"  [cyan]{name}[/cyan]: {email}")
        except Exception:
            console.print(f"  [cyan]{name}[/cyan]: [dim](invalid)[/dim]")


@profile_app.command("delete")
def profile_delete(
    profile: str = typer.Argument(..., help="Profile name to delete"),
    confirm: bool = typer.Option(
        False,
        "--confirm",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Delete a profile and its credentials."""
    from notebooklm_tools.services.auth import AuthManager

    auth = AuthManager(profile)

    # Allow deleting invalid profiles (check if name is in list_profiles)
    if profile not in AuthManager.list_profiles():
        console.print(f"[red]Error:[/red] Profile '{profile}' not found")
        raise typer.Exit(1)

    if not confirm:
        typer.confirm(
            f"Are you sure you want to delete profile '{profile}'?",
            abort=True,
        )

    auth.delete_profile()
    console.print(f"[green]✓[/green] Deleted profile: {profile}")


@profile_app.command("rename")
def profile_rename(
    old_name: str = typer.Argument(..., help="Current profile name"),
    new_name: str = typer.Argument(..., help="New profile name"),
) -> None:
    """Rename an authentication profile."""
    from notebooklm_tools.core.exceptions import NLMError
    from notebooklm_tools.services.auth import AuthManager

    # Check if old profile exists
    old_auth = AuthManager(old_name)
    if not old_auth.profile_exists():
        console.print(f"[red]Error:[/red] Profile '{old_name}' not found")
        raise typer.Exit(1)

    # Check if new profile name already exists
    new_auth = AuthManager(new_name)
    if new_auth.profile_exists():
        console.print(f"[red]Error:[/red] Profile '{new_name}' already exists")
        raise typer.Exit(1)

    try:
        # Load old profile data
        profile_data = old_auth.load_profile()

        # Save with new name
        new_auth.save_profile(
            cookies=profile_data.cookies,
            csrf_token=profile_data.csrf_token,
            session_id=profile_data.session_id,
            email=profile_data.email,
            build_label=profile_data.build_label,
            base_host=profile_data.base_host,
        )

        # Delete old profile
        old_auth.delete_profile()

        console.print(f"[green]✓[/green] Renamed profile from '{old_name}' to '{new_name}'")
    except NLMError as e:
        console.print(f"[red]Error:[/red] {e.message}")
        if e.hint:
            console.print(f"\n[dim]Hint: {e.hint}[/dim]")
        raise typer.Exit(1) from e


@login_app.command("switch")
def login_switch(
    profile: str = typer.Argument(..., help="Profile name to switch to"),
) -> None:
    """Switch the default profile for all commands."""
    from notebooklm_tools.services.auth import AuthManager
    from notebooklm_tools.utils.config import get_config, save_config

    # Check if profile exists
    auth = AuthManager(profile)
    if not auth.profile_exists():
        console.print(f"[red]Error:[/red] Profile '{profile}' not found")
        console.print("\nAvailable profiles:")
        for name in AuthManager.list_profiles():
            console.print(f"  [cyan]{name}[/cyan]")
        raise typer.Exit(1)

    # Update config
    config = get_config()
    old_profile = config.auth.default_profile
    config.auth.default_profile = profile
    save_config(config)

    # Show confirmation with account info
    try:
        p = auth.load_profile()
        email = p.email or "Unknown"
        console.print(f"[green]✓[/green] Switched default profile to [cyan]{profile}[/cyan]")
        console.print(f"  Account: {email}")
        if old_profile != profile:
            console.print(f"  [dim]Previous: {old_profile}[/dim]")
    except Exception:
        console.print(f"[green]✓[/green] Switched default profile to [cyan]{profile}[/cyan]")


@auth_app.command("refresh")
def auth_refresh(
    profile: str = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to refresh (default: the configured default profile).",
    ),
) -> None:
    """Refresh a session non-interactively so Google reissues its cookies.

    Runs a headless-browser pass against the saved Chrome profile, which makes
    Google reissue the short-lived cookies (``*PSIDTS``) that keep a session
    alive. Unlike ``nlm login``, this needs no user interaction, so schedulers
    (cron/launchd) can keep an unattended session alive without an interactive
    re-login. Exits non-zero if the refresh fails, so scripts can react.
    """
    import os

    from notebooklm_tools.utils.config import get_config

    if os.environ.get("NOTEBOOKLM_COOKIES"):
        console.print(
            "[yellow]![/yellow] NOTEBOOKLM_COOKIES is set and overrides saved "
            "credentials, so a refresh won't take effect. Update that value "
            "(e.g. in your MCP config) instead."
        )
        raise typer.Exit(1)

    profile_name = profile or get_config().auth.default_profile

    from notebooklm_tools.utils.auth_browser import run_headless_auth

    with console.status(f"Refreshing session for profile '{profile_name}'..."):
        try:
            tokens = run_headless_auth(profile_name=profile_name)
        except Exception as exc:
            console.print(f"[red]✗[/red] Refresh failed: {exc}")
            raise typer.Exit(1) from exc

    if not tokens:
        console.print(
            f"[red]✗[/red] Could not refresh profile '{profile_name}'. The saved "
            "Chrome profile may be missing or its login expired — run 'nlm login' "
            "to re-authenticate."
        )
        raise typer.Exit(1)

    console.print(f"[green]✓[/green] Session refreshed for profile '{profile_name}'.")


# Register profile commands under login
login_app.add_typer(profile_app, name="profile")

# Register login app with nested profile commands
app.add_typer(login_app, name="login")

# Register non-interactive session maintenance commands
app.add_typer(auth_app, name="auth", help="Session auth maintenance")

# Register noun-first subcommands (existing structure)
app.add_typer(notebook_app, name="notebook", help="Manage notebooks")
app.add_typer(label_app, name="label", help="Manage source labels")
app.add_typer(note_app, name="note", help="Manage notes")
app.add_typer(source_app, name="source", help="Manage sources")
app.add_typer(chats_app, name="chats", help="Manage chat sessions")
app.add_typer(chat_app, name="chat", help="Configure chat settings")
app.add_typer(studio_app, name="studio", help="Manage studio artifacts")
app.add_typer(research_app, name="research", help="Research and discover sources")
app.add_typer(alias_app, name="alias", help="Manage ID aliases")
app.add_typer(config_app, name="config", help="Manage configuration")
app.add_typer(download_app, name="download", help="Download artifacts (audio, video, etc)")
app.add_typer(share_app, name="share", help="Manage notebook sharing")
app.add_typer(export_app, name="export", help="Export artifacts to Google Docs/Sheets")
app.add_typer(skill_app, name="skill", help="Install skills for AI tools")
app.add_typer(setup_app, name="setup", help="Configure MCP server for AI tools")
app.add_typer(doctor_app, name="doctor", help="Diagnose installation and configuration")
app.add_typer(batch_app, name="batch", help="Batch operations across notebooks")
app.add_typer(cross_app, name="cross", help="Cross-notebook queries")
app.add_typer(pipeline_app, name="pipeline", help="Run multi-step pipelines")
app.add_typer(tag_app, name="tag", help="Manage notebook tags")
app.add_typer(usage_app, name="usage", help="Show remaining plan usage and reset times")

# Generation commands as top-level
app.add_typer(audio_app, name="audio", help="Create audio overviews")
app.add_typer(report_app, name="report", help="Create reports")
app.add_typer(quiz_app, name="quiz", help="Create quizzes")
app.add_typer(flashcards_app, name="flashcards", help="Create flashcards")
app.add_typer(mindmap_app, name="mindmap", help="Create and manage mind maps")
app.add_typer(slides_app, name="slides", help="Create slide decks")
app.add_typer(infographic_app, name="infographic", help="Create infographics")
app.add_typer(video_app, name="video", help="Create video overviews")
app.add_typer(data_table_app, name="data-table", help="Create data tables")

# Auth is now under login (removed auth_app registration)

# Register verb-first subcommands (alternative structure)
app.add_typer(create_app, name="create", help="Create resources (notebooks, audio, video, etc)")
app.add_typer(list_app, name="list", help="List resources (notebooks, sources, artifacts)")
app.add_typer(get_app, name="get", help="Get details about resources")
app.add_typer(delete_app, name="delete", help="Delete resources (notebooks, sources, artifacts)")
app.add_typer(add_app, name="add", help="Add resources (sources to notebooks)")
app.add_typer(rename_app, name="rename", help="Rename resources")
app.add_typer(status_app, name="status", help="Check status of resources")
app.add_typer(describe_app, name="describe", help="Get AI-generated descriptions and summaries")
app.add_typer(query_app, name="query", help="Chat with notebook sources")
app.add_typer(sync_app, name="sync", help="Sync resources (Drive sources)")
app.add_typer(content_app, name="content", help="Get raw content from sources")
app.add_typer(stale_app, name="stale", help="List stale resources that need syncing")
app.add_typer(configure_app, name="configure", help="Configure settings")
app.add_typer(set_app, name="set", help="Set values (aliases, config)")
app.add_typer(show_app, name="show", help="Show information")
app.add_typer(install_app, name="install", help="Install resources (skills)")
app.add_typer(uninstall_app, name="uninstall", help="Uninstall resources (skills)")
app.add_typer(update_app, name="update", help="Update resources (skills)")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit",
    ),
    ai: bool = typer.Option(
        False,
        "--ai",
        help="Output AI-friendly documentation for this CLI",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging (shows raw API responses)",
    ),
) -> None:
    """
    NLM - Command-line interface for Google NotebookLM.

    Use 'nlm <command> --help' for help on specific commands.
    """
    if debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(name)s %(levelname)s: %(message)s",
        )
        logging.getLogger("notebooklm_mcp.api").setLevel(logging.DEBUG)

    if version:
        from notebooklm_tools.cli.utils import check_for_updates

        console.print(f"nlm version {__version__}")

        # Check for updates when showing version
        update_available, latest = check_for_updates()
        if not (update_available and latest):
            console.print("[dim]You are on the latest version.[/dim]")
        raise typer.Exit()

    if ai:
        from notebooklm_tools.cli.ai_docs import print_ai_docs

        print_ai_docs()
        raise typer.Exit()

    # Show help if no command provided
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


def cli_main():
    """Main CLI entry point with error handling."""
    import sys

    from notebooklm_tools.utils.io_encoding import configure_stdio_utf8_on_windows

    configure_stdio_utf8_on_windows()

    try:
        app()
    except Exception as e:
        # Import here to avoid circular dependencies
        from notebooklm_tools.core.errors import ClientAuthenticationError
        from notebooklm_tools.core.exceptions import (
            AuthenticationError,
            NLMError,
        )

        # Handle authentication errors cleanly
        if isinstance(e, (AuthenticationError, ClientAuthenticationError)):
            console.print("\n[red]✗ Authentication Error[/red]")
            console.print(f"  {str(e)}")
            console.print("\n[yellow]→[/yellow] Run [cyan]nlm login[/cyan] to re-authenticate\n")
            sys.exit(1)

        # Handle other NLM errors cleanly
        elif isinstance(e, NLMError):
            console.print(f"\n[red]✗ Error:[/red] {e.message}")
            if e.hint:
                console.print(f"[dim]{e.hint}[/dim]\n")
            sys.exit(1)

        # For unexpected errors, show the traceback
        else:
            raise
    finally:
        try:
            from notebooklm_tools.cli.utils import print_update_notification

            print_update_notification()
        except Exception:
            pass


if __name__ == "__main__":
    cli_main()
