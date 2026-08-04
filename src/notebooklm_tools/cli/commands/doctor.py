"""Diagnostic command for troubleshooting Gemini Notebook MCP setup."""

import platform
import shutil

import typer

from notebooklm_tools.cli.utils import make_console

console = make_console()
app = typer.Typer(
    name="doctor",
    help="Diagnose Gemini Notebook MCP installation and configuration",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show additional diagnostic details",
    ),
) -> None:
    """
    Run diagnostics on your Gemini Notebook MCP installation.

    Checks installation, authentication, Chrome profile, and AI tool
    configurations. Suggests fixes for common issues.

    Examples:
        nlm doctor
        nlm doctor --verbose
    """
    if ctx.invoked_subcommand is not None:
        return

    console.print("[bold]Gemini Notebook MCP Doctor[/bold]\n")

    # Check WSL first - it affects other checks
    is_wsl = _check_wsl(verbose)
    console.print()

    all_ok = True
    all_ok &= _check_installation(verbose)
    console.print()
    all_ok &= _check_authentication(verbose)
    console.print()
    if is_wsl:
        all_ok &= _check_wsl_chrome(verbose)
    else:
        all_ok &= _check_chrome(verbose)
    console.print()
    all_ok &= _check_clients(verbose)
    console.print()

    if all_ok:
        console.print("[green]✓ All checks passed![/green]")
    else:
        console.print("[yellow]Some issues found.[/yellow] See suggestions above.")


@app.command("auth-replay")
def auth_replay(
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile to diagnose (defaults to configured profile)",
    ),
    no_cdp: bool = typer.Option(
        False,
        "--no-cdp",
        help="Skip the in-browser CDP fetch probe",
    ),
    timeout: float = typer.Option(
        15.0,
        "--timeout",
        help="Timeout in seconds for each replay lane",
    ),
) -> None:
    """Diagnose cookie replay vs browser-bound auth failures.

    This compares four lanes:
    1. saved cookies through normal httpx,
    2. httpx after a forced Google RotateCookies call,
    3. cookies freshly re-extracted from a live, logged-in browser session,
       replayed through normal httpx (distinguishes stale saved cookies
       from genuine device-bound replay),
    4. an optional in-page CDP fetch from that same browser session.

    Lanes 3 and 4 are skipped together via --no-cdp.
    """
    from notebooklm_tools.services.auth import diagnose_auth_replay

    console.print("[bold]NotebookLM Auth Replay Diagnostic[/bold]\n")
    report = diagnose_auth_replay(profile=profile, include_cdp=not no_cdp, timeout=timeout)

    console.print(f"Profile: [cyan]{report.profile}[/cyan]")
    console.print(f"Verdict: [bold]{report.verdict}[/bold]\n")

    for probe in report.probes:
        if not probe.attempted:
            status = "[dim]skipped[/dim]"
        elif probe.valid:
            status = "[green]pass[/green]"
        else:
            status = "[red]fail[/red]"
        console.print(f"  {probe.name}: {status}")
        if probe.notebook_count is not None:
            console.print(f"    notebooks: {probe.notebook_count}")
        if probe.detail:
            console.print(f"    [dim]{probe.detail}[/dim]")
        if probe.error:
            console.print(f"    [red]{probe.error}[/red]")

    console.print(f"\nRecommendation: {report.recommendation}")

    if report.verdict in {"not_configured", "profile_load_error", "all_failed"}:
        raise typer.Exit(2)


def _check_installation(verbose: bool) -> bool:
    """Check that the package and binaries are properly installed."""
    console.print("[bold]Installation[/bold]")
    ok = True

    # Package version
    try:
        from notebooklm_tools import __version__

        console.print(f"  notebooklm-mcp-cli: [green]{__version__}[/green]")
    except ImportError:
        console.print("  notebooklm-mcp-cli: [red]not importable[/red]")
        ok = False

    # Binary paths
    for cmd in ["nlm", "notebooklm-mcp"]:
        path = shutil.which(cmd)
        if path:
            console.print(f"  {cmd}: [green]{path}[/green]")
        else:
            console.print(f"  {cmd}: [red]not found in PATH[/red]")
            ok = False

    # Python version
    if verbose:
        import sys

        console.print(f"  python: [dim]{sys.executable} ({platform.python_version()})[/dim]")
        console.print(f"  platform: [dim]{platform.system()} {platform.machine()}[/dim]")

    return ok


def _check_authentication(verbose: bool) -> bool:
    """Check authentication status."""
    console.print("[bold]Authentication[/bold]")
    ok = True

    from notebooklm_tools.services.auth import AuthManager
    from notebooklm_tools.utils.config import get_config

    config = get_config()
    default_profile = config.auth.default_profile
    profiles = AuthManager.list_profiles()

    if not profiles:
        console.print("  Profiles: [red]none[/red]")
        console.print("  [yellow]→[/yellow] Run [cyan]nlm login[/cyan] to authenticate")
        return False

    console.print(f"  Default profile: [cyan]{default_profile}[/cyan]")
    console.print(f"  Profiles found: {len(profiles)}")

    # Check default profile
    try:
        auth = AuthManager(default_profile)
        if auth.profile_exists():
            profile = auth.load_profile()

            has_cookies = bool(profile.cookies)
            has_csrf = bool(profile.csrf_token)
            email = profile.email or "unknown"

            if has_cookies:
                console.print(f"  Cookies: [green]present[/green] ({len(profile.cookies)} cookies)")
            else:
                console.print("  Cookies: [red]missing[/red]")
                ok = False

            console.print(
                f"  CSRF token: {'[green]yes[/green]' if has_csrf else '[yellow]no[/yellow] (will auto-extract)'}"
            )
            console.print(f"  Account: {email}")

            if verbose:
                # Show last validated time
                last_validated = getattr(profile, "last_validated", None)
                if last_validated:
                    console.print(f"  Last validated: [dim]{last_validated}[/dim]")
        else:
            console.print(f"  Profile '{default_profile}': [red]not found[/red]")
            console.print("  [yellow]→[/yellow] Run [cyan]nlm login[/cyan] to create it")
            ok = False
    except Exception as e:
        console.print(f"  Profile '{default_profile}': [red]error loading[/red] ({e})")
        ok = False

    # Show other profiles
    if verbose and len(profiles) > 1:
        console.print(f"  Other profiles: {', '.join(p for p in profiles if p != default_profile)}")

    return ok


def _check_wsl(verbose: bool) -> bool:
    """Check if running in WSL and report WSL-specific diagnostics."""
    from notebooklm_tools.utils.wsl import check_firewall_rule, get_windows_host_ip, is_wsl

    if not is_wsl():
        return False

    console.print("[bold]WSL2 Environment[/bold]")
    console.print("  Status: [green]detected[/green]")

    windows_ip = get_windows_host_ip()
    if windows_ip:
        console.print(f"  Windows host IP: [green]{windows_ip}[/green]")
    else:
        console.print("  Windows host IP: [red]not found[/red]")
        console.print("  [yellow]→[/yellow] Check /etc/resolv.conf")

    # Check Windows Firewall
    if check_firewall_rule():
        console.print("  Firewall rule: [green]exists[/green]")
    else:
        console.print("  Firewall rule: [yellow]not found[/yellow]")
        console.print("  [yellow]→[/yellow] Run with --wsl to auto-create, or:")
        console.print("     [dim]nlm login --wsl[/dim]")

    return True


def _check_wsl_chrome(verbose: bool) -> bool:
    """Check Windows Chrome accessibility from WSL."""
    console.print("[bold]Chrome (WSL2)[/bold]")
    ok = True

    from notebooklm_tools.utils.wsl import (
        diagnose_wsl_connectivity,
        find_windows_chrome,
        get_windows_host_ip,
    )

    chrome_path = find_windows_chrome()
    if chrome_path:
        console.print("  Windows Chrome: [green]found[/green]")
        console.print(f"  [dim]{chrome_path}[/dim]")
    else:
        console.print("  Windows Chrome: [red]not found[/red]")
        console.print("  [yellow]→[/yellow] Install Chrome on Windows side")
        console.print("    or use [cyan]nlm login --manual[/cyan] with cookie file")
        ok = False

    # Run connectivity diagnostics
    windows_ip = get_windows_host_ip()
    if windows_ip and verbose:
        console.print("\n  [dim]Running connectivity diagnostics...[/dim]")
        diagnostics = diagnose_wsl_connectivity(windows_ip)
        for test_name, result in diagnostics.get("tests", {}).items():
            status = (
                "[green]✓[/green]"
                if "PASS" in str(result).upper() or result in ["EXISTS", "YES"]
                else "[red]✗[/red]"
            )
            console.print(f"    {status} {test_name}: {result}")

    # Check for saved profile (same as regular mode)
    from notebooklm_tools.utils.config import get_storage_dir

    chrome_profiles_dir = get_storage_dir() / "chrome-profiles"
    has_profile = False

    if chrome_profiles_dir.exists():
        for profile_dir in chrome_profiles_dir.iterdir():
            if profile_dir.is_dir() and (profile_dir / "Default").exists():
                has_profile = True
                console.print(f"  Saved profile: [green]{profile_dir.name}[/green]")

    if has_profile:
        console.print("  Headless auth: [green]available[/green]")
    else:
        console.print("  Headless auth: [yellow]not available[/yellow]")
        console.print(
            "  [dim]Run [cyan]nlm login --wsl[/cyan] to authenticate (saves Windows Chrome profile)[/dim]"
        )

    return ok


def _check_chrome(verbose: bool) -> bool:
    """Check Chrome installation and saved profile."""
    console.print("[bold]Browser[/bold]")
    ok = True

    # Browser binary
    from notebooklm_tools.utils.cdp import get_browser_display_name, get_chrome_path

    chrome_path = get_chrome_path()
    browser_name = get_browser_display_name() if chrome_path else "Browser"

    if chrome_path:
        console.print(f"  {browser_name}: [green]installed[/green]")
        if verbose:
            console.print(f"  [dim]{chrome_path}[/dim]")
    else:
        console.print("  Browser: [red]not found[/red]")
        console.print("  [yellow]→[/yellow] A supported browser is required for authentication")
        ok = False

    # Saved Chrome profile
    from notebooklm_tools.utils.config import get_storage_dir

    chrome_profiles_dir = get_storage_dir() / "chrome-profiles"
    has_profile = False

    if chrome_profiles_dir.exists():
        for profile_dir in chrome_profiles_dir.iterdir():
            if profile_dir.is_dir() and (profile_dir / "Default").exists():
                has_profile = True
                console.print(f"  Saved profile: [green]{profile_dir.name}[/green]")
                if verbose:
                    console.print(f"  [dim]{profile_dir}[/dim]")

    # Also check legacy location
    legacy_chrome = get_storage_dir() / "chrome-profile"
    if legacy_chrome.exists() and (legacy_chrome / "Default").exists():
        has_profile = True
        if verbose:
            console.print(f"  Legacy profile: [dim]{legacy_chrome}[/dim]")

    if has_profile:
        console.print("  Headless auth: [green]available[/green] (saved Google login)")
    else:
        console.print("  Headless auth: [yellow]not available[/yellow] (no saved profile)")
        console.print("  [dim]Run nlm login once to save Chrome profile for headless refresh[/dim]")

    return ok


def _check_clients(verbose: bool) -> bool:
    """Check AI tool MCP configurations."""
    console.print("[bold]AI Tool Configurations[/bold]")

    # Import setup module for config detection
    import subprocess

    from notebooklm_tools.cli.commands.setup import (
        CLIENT_REGISTRY,
        _claude_desktop_profile_paths,
        _cursor_config_path,
        _gemini_config_path,
        _is_configured,
        _read_json_config,
        _windsurf_config_path,
    )

    configured_count = 0
    total_count = 0

    for client_id, info in CLIENT_REGISTRY.items():
        if not info["has_auto_setup"]:
            continue
        total_count += 1

        status = None

        if client_id == "claude-code":
            claude_cmd = shutil.which("claude")
            if claude_cmd:
                try:
                    result = subprocess.run(
                        [claude_cmd, "mcp", "list"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        encoding="utf-8",
                        errors="replace",
                    )
                    if result.stdout and "notebooklm" in result.stdout.lower():
                        status = True
                except (subprocess.TimeoutExpired, OSError):
                    pass
            elif not claude_cmd:
                if verbose:
                    console.print(f"  {info['name']}: [dim]not installed[/dim]")
                continue

        elif client_id == "claude-desktop":
            paths = _claude_desktop_profile_paths()
            status = bool(paths) and any(
                _is_configured(_read_json_config(path)) for path in paths.values()
            )

        elif client_id == "gemini":
            path = _gemini_config_path()
            config = _read_json_config(path)
            status = _is_configured(config, "notebooklm")

        elif client_id == "cursor":
            path = _cursor_config_path()
            config = _read_json_config(path)
            status = _is_configured(config)

        elif client_id == "windsurf":
            path = _windsurf_config_path()
            config = _read_json_config(path)
            status = _is_configured(config)

        if status is True:
            console.print(f"  {info['name']}: [green]configured[/green]")
            configured_count += 1
        elif status is False:
            console.print(
                f"  {info['name']}: [yellow]not configured[/yellow]  → [cyan]nlm setup add {client_id}[/cyan]"
            )
        # None means we couldn't determine (already printed)

    if configured_count == 0:
        console.print("\n  [yellow]No AI tools configured.[/yellow]")
        console.print("  Run [cyan]nlm setup add <client>[/cyan] to configure one.")
        return False

    return True
