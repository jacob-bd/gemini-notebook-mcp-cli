"""WSL2 utility functions for cross-platform authentication support.

WSL2 cannot directly launch GUI applications without causing terminal corruption.
This module provides helpers to launch Windows Chrome from WSL and manage
the cross-boundary authentication flow.

Security Note:
--------------
This module launches Chrome with --remote-debugging-address=0.0.0.0 to allow
connections from the WSL2 virtual network. This differs from the standard
H-3 remediation (which restricts to 127.0.0.1) because WSL2 uses a virtual
network bridge that requires cross-boundary access.

Mitigations in place:
- Windows Firewall limits connections to LocalSubnet (WSL virtual network only)
- Temporary Chrome profiles are used and cleaned up after authentication
- Chrome remote debugging is only active during explicit nlm login --wsl
- No other network hosts can reach the debugging port

See: docs/SECURITY_REMEDIATION_PLAN.md (H-3) for original security context.
"""

import contextlib
import logging
import shutil
import subprocess
import time
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


DEFAULT_WSL_CDP_PORT = 9222
WINDOWS_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def is_wsl() -> bool:
    """Detect if running inside Windows Subsystem for Linux.

    Returns:
        True if WSL environment detected, False otherwise.
    """
    # Check for WSLInterop file (existence indicates WSL2)
    wslinterop = Path("/proc/sys/fs/binfmt_misc/WSLInterop")
    if wslinterop.exists():
        return True

    # Check kernel version string for microsoft
    try:
        version = Path("/proc/version").read_text().lower()
        return "microsoft" in version or "wsl" in version
    except (OSError, FileNotFoundError):
        pass

    return False


def _is_mirrored_networking() -> bool:
    """Return whether WSL is using mirrored networking mode."""
    try:
        result = subprocess.run(
            ["wslinfo", "--networking-mode"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False

    return result.stdout.strip().casefold() == "mirrored"


def get_windows_host_ip() -> str | None:
    """Get the Windows host IP address from WSL.

    In mirrored mode, Windows is reachable through the shared loopback
    interface. In NAT mode, the Windows host is the default gateway.

    Returns:
        IP address string (e.g., "172.20.112.1") or None if not in WSL.
    """
    if not is_wsl():
        return None

    if _is_mirrored_networking():
        return "127.0.0.1"

    # Method 1: Get default gateway (most reliable for Chrome binding)
    try:
        result = subprocess.run(
            ["ip", "route"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("default via"):
                # Format: "default via 172.25.144.1 dev eth0"
                ip = line.split()[2]
                logger.debug(f"Windows host IP from default gateway: {ip}")
                return ip
    except (subprocess.CalledProcessError, IndexError, FileNotFoundError) as e:
        logger.debug(f"Could not get IP from default gateway: {e}")

    # Method 2: Fallback to resolv.conf nameserver
    try:
        result = subprocess.run(
            ["grep", "nameserver", "/etc/resolv.conf"],
            capture_output=True,
            text=True,
            check=True,
        )
        # Format: "nameserver 10.255.255.254"
        ip = result.stdout.strip().split()[1]
        logger.debug(f"Windows host IP from resolv.conf: {ip}")
        return ip
    except (subprocess.CalledProcessError, IndexError, FileNotFoundError) as e:
        logger.warning(f"Could not determine Windows host IP: {e}")
        return None


def find_windows_chrome() -> str | None:
    """Find Chrome executable path on Windows side from WSL.

    Searches common Chrome installation locations.

    Returns:
        Windows path (e.g., "C:\\...\\chrome.exe") or None if not found.
    """
    if not is_wsl():
        return None

    for path in WINDOWS_CHROME_PATHS:
        # Convert Windows path to WSL path (/mnt/c/...)
        wsl_path = Path("/mnt/c") / path[3:].replace("\\", "/")
        if wsl_path.exists():
            logger.debug(f"Found Windows Chrome at: {path}")
            return path

    # Fallback: Try to find via PATH
    try:
        result = subprocess.run(
            ["which", "chrome.exe"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            windows_path = result.stdout.strip().replace("/mnt/c/", "C:\\").replace("/", "\\")
            logger.debug(f"Found Windows Chrome via PATH: {windows_path}")
            return windows_path
    except Exception as e:
        logger.debug(f"which chrome.exe failed: {e}")

    return None


def launch_windows_chrome(
    port: int = DEFAULT_WSL_CDP_PORT, debug: bool = False
) -> subprocess.Popen:
    """Launch Chrome on Windows side from WSL.

    Args:
        port: Remote debugging port to use.
        debug: If True, capture Chrome's stderr for diagnostics.

    Returns:
        subprocess.Popen handle to the Windows Chrome process.

    Raises:
        RuntimeError: If Chrome cannot be launched.
    """
    if not is_wsl():
        raise RuntimeError("Not running in WSL environment")

    # Check if Chrome is already running - this is a HARD REQUIREMENT
    # because Chrome uses a single-instance model
    try:
        result = subprocess.run(
            ["pgrep", "-f", "chrome.exe"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Try taskkill to close Chrome
            try:
                subprocess.run(
                    ["taskkill", "/f", "/im", "chrome.exe"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                time.sleep(2)  # Wait for Chrome to close
                # Check again
                result2 = subprocess.run(
                    ["pgrep", "-f", "chrome.exe"],
                    capture_output=True,
                    text=True,
                )
                if result2.returncode == 0 and result2.stdout.strip():
                    raise RuntimeError(
                        "Chrome is already running and could not be closed. "
                        "\n\nPlease:"
                        "\n  1. Close ALL Chrome windows and tabs manually"
                        "\n  2. Run: taskkill /f /im chrome.exe  (in Windows PowerShell Admin)"
                        "\n  3. Then retry: nlm login --wsl"
                    )
            except Exception as e:
                if "Chrome is already running" in str(e):
                    raise
                logger.debug(f"Could not terminate existing Chrome: {e}")
    except RuntimeError:
        raise
    except Exception:
        pass  # pgrep might not be available, continue anyway

    chrome_path = find_windows_chrome()
    if not chrome_path:
        raise RuntimeError(
            "Chrome not found on Windows side. "
            "Common locations checked:\n  " + "\n  ".join(WINDOWS_CHROME_PATHS)
        )

    # Convert Windows path to WSL executable path
    # C:\Program Files\... -> /mnt/c/Program Files/...
    wsl_chrome = Path("/mnt/c") / chrome_path[3:].replace("\\", "/")

    # Create a temp profile directory on the WINDOWS filesystem.
    # Using WSL's /tmp causes "Profile error occurred" because Chrome
    # struggles with UNC paths (\\wsl.localhost\...) for its profile dir.
    import tempfile

    try:
        win_temp_base = subprocess.run(
            ["powershell.exe", "-Command", "echo $env:TEMP"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        # Create a unique subdir name
        import uuid

        windows_temp = f"{win_temp_base}\\nlm-chrome-{uuid.uuid4().hex[:8]}"
        # Convert to WSL path for cleanup tracking
        temp_dir = subprocess.run(
            ["wslpath", "-u", windows_temp],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        # Fallback to WSL temp (may cause profile error but won't crash)
        temp_dir = tempfile.mkdtemp(prefix="nlm-chrome-")
        windows_temp = subprocess.run(
            ["wslpath", "-w", temp_dir],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    args = [
        str(wsl_chrome),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={windows_temp}",  # CRITICAL: Fresh profile for separate instance
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-breakpad",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-features=ChromeCleanup,TranslateUI,PrivacySandboxSettings4",
        "--disable-hang-monitor",
        "--disable-ipc-flooding-protection",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-renderer-backgrounding",
        "--force-color-profile=srgb",
        "--metrics-recording-only",
        "--safebrowsing-disable-auto-update",
        "--password-store=basic",  # Don't try to use system password store
        "--use-mock-keychain",  # Use mock keychain on macOS/Windows
    ]

    stderr_arg = None if debug else subprocess.DEVNULL
    stdout_arg = None if debug else subprocess.DEVNULL

    logger.info(f"Launching Windows Chrome on port {port}")
    logger.debug(f"Chrome temp profile: {temp_dir}")
    try:
        process = subprocess.Popen(
            args,
            stdout=stdout_arg,
            stderr=stderr_arg,
            start_new_session=True,  # Prevent signal propagation
        )
        # Store temp_dir for cleanup in terminate_windows_chrome
        process._nlm_temp_dir = temp_dir  # type: ignore[attr-defined]
        logger.debug(f"Chrome process started: PID {process.pid}")
        return process
    except Exception as e:
        # Clean up temp dir on launch failure
        with contextlib.suppress(Exception):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"Failed to launch Chrome: {e}") from e


def wait_for_cdp(cdp_url: str, timeout: int = 30) -> bool:
    """Wait for Chrome DevTools Protocol to be ready.

    Args:
        cdp_url: Full CDP HTTP URL (e.g., "http://172.20.112.1:9222")
        timeout: Maximum seconds to wait.

    Returns:
        True if CDP is ready, False if timeout.
    """
    import urllib.parse

    parsed = urllib.parse.urlparse(cdp_url)
    base_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"

    logger.debug(f"Waiting for CDP at {base_url}")
    start = time.time()
    last_error = None
    while time.time() - start < timeout:
        try:
            # Try without headers first (simplest approach)
            response = httpx.get(f"{base_url}/json", timeout=2, follow_redirects=True)
            if response.status_code == 200:
                logger.debug(f"CDP ready after {time.time() - start:.1f}s")
                return True
            else:
                logger.debug(f"CDP returned status {response.status_code}")
        except Exception as e:
            last_error = str(e)
            pass
        time.sleep(0.5)

    logger.warning(f"CDP not ready after {timeout}s (last error: {last_error})")
    return False


def terminate_windows_chrome(process: subprocess.Popen | None) -> bool:
    """Terminate a Windows Chrome process launched from WSL.

    Also cleans up the temporary Chrome profile directory if one was created.

    Args:
        process: subprocess.Popen handle from launch_windows_chrome()

    Returns:
        True if termination was attempted, False otherwise.
    """
    if process is None:
        return False

    # Get temp_dir before terminating (in case process._nlm_temp_dir is cleared)
    temp_dir = getattr(process, "_nlm_temp_dir", None)

    try:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        logger.debug(f"Terminated Chrome process {process.pid}")
    except Exception as e:
        logger.warning(f"Failed to terminate Chrome: {e}")

    # Clean up temp profile directory
    if temp_dir:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.debug(f"Cleaned up Chrome temp profile: {temp_dir}")
        except Exception as e:
            logger.debug(f"Failed to cleanup temp dir {temp_dir}: {e}")

    return True


def get_wsl_cdp_url(port: int = DEFAULT_WSL_CDP_PORT) -> str | None:
    """Get the CDP URL for connecting to Windows Chrome from WSL.

    Args:
        port: The port Chrome is listening on.

    Returns:
        Full CDP URL (e.g., "http://172.20.112.1:9222") or None.
    """
    ip = get_windows_host_ip()
    if not ip:
        return None
    return f"http://{ip}:{port}"


def _get_powershell_path() -> Path | None:
    """Find PowerShell executable on Windows side from WSL."""
    # Try PowerShell 7 (pwsh) first, then Windows PowerShell
    candidates = [
        "/mnt/c/Program Files/PowerShell/7/pwsh.exe",
        "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
        "/mnt/c/Windows/SysWOW64/WindowsPowerShell/v1.0/powershell.exe",
    ]
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return path
    return None


def check_firewall_rule(port: int = DEFAULT_WSL_CDP_PORT) -> bool:
    """Check if Windows Firewall allows inbound connections on the given port.

    Args:
        port: Port number to check.

    Returns:
        True if a rule exists, False otherwise.
    """
    if not is_wsl():
        return False

    ps_path = _get_powershell_path()
    if not ps_path:
        logger.debug("PowerShell not found")
        return False

    # Check if rule exists
    check_cmd = (
        f"Get-NetFirewallRule -DisplayName 'NotebookLM-CDP-{port}' "
        "-ErrorAction SilentlyContinue | Select-Object -First 1"
    )

    try:
        result = subprocess.run(
            [str(ps_path), "-Command", check_cmd],
            capture_output=True,
            text=True,
            errors="replace",
        )
        exists = result.returncode == 0 and result.stdout.strip()
        logger.debug(f"Firewall rule check for port {port}: {exists}")
        return exists
    except Exception as e:
        logger.warning(f"Failed to check firewall rule: {e}")
        return False


def create_firewall_rule(port: int = DEFAULT_WSL_CDP_PORT) -> tuple[bool, str]:
    """Create Windows Firewall rule to allow inbound connections from WSL.

    Args:
        port: Port number to allow.

    Returns:
        Tuple of (success: bool, message: str).
    """
    if not is_wsl():
        return False, "Not running in WSL"

    ps_path = _get_powershell_path()
    if not ps_path:
        return False, "PowerShell not found on Windows side"

    rule_name = f"NotebookLM-CDP-{port}"

    try:
        # Build PowerShell command to create firewall rule
        # This will trigger UAC prompt if not running as admin
        logger.info(f"Creating Windows Firewall rule for port {port}")

        ps_cmd = (
            f"New-NetFirewallRule -DisplayName '{rule_name}' "
            f"-Direction Inbound -Action Allow -Protocol TCP -LocalPort {port} "
            f"-RemoteAddress LocalSubnet "
            f"-Description 'Allow WSL2 to connect to Chrome DevTools Protocol for NotebookLM MCP'"
        )

        result = subprocess.run(
            [str(ps_path), "-Command", ps_cmd],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            msg = f"Created firewall rule '{rule_name}'"
            logger.info(msg)
            return True, msg
        else:
            error = result.stderr.strip() if result.stderr else "Unknown error"
            logger.warning(f"Failed to create firewall rule: {error}")

            # Check if it's a permission issue
            if (
                "access" in error.lower()
                or "permission" in error.lower()
                or "privilege" in error.lower()
            ):
                return False, (
                    "Administrator privileges required.\n"
                    "Please run in Windows PowerShell (as Administrator):\n"
                    f"  New-NetFirewallRule -DisplayName '{rule_name}' "
                    f"-Direction Inbound -Action Allow -Protocol TCP -LocalPort {port}"
                )
            return False, error

    except Exception as e:
        logger.error(f"Exception creating firewall rule: {e}")
        return False, str(e)


def remove_firewall_rule(port: int = DEFAULT_WSL_CDP_PORT) -> bool:
    """Remove the Windows Firewall rule for the given port.

    Args:
        port: Port number.

    Returns:
        True if successful, False otherwise.
    """
    if not is_wsl():
        return False

    ps_path = _get_powershell_path()
    if not ps_path:
        return False

    rule_name = f"NotebookLM-CDP-{port}"
    ps_cmd = f"Remove-NetFirewallRule -DisplayName '{rule_name}' -ErrorAction SilentlyContinue"

    try:
        result = subprocess.run(
            [str(ps_path), "-Command", ps_cmd],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"Failed to remove firewall rule: {e}")
        return False


def diagnose_wsl_connectivity(host_ip: str, port: int = DEFAULT_WSL_CDP_PORT) -> dict:
    """Run diagnostics to troubleshoot WSL->Windows connectivity issues.

    Args:
        host_ip: The Windows host IP to test.
        port: The port to test.

    Returns:
        Dictionary with diagnostic results.
    """
    results = {
        "wsl_detected": is_wsl(),
        "windows_ip": host_ip,
        "port": port,
        "tests": {},
    }

    # Test 1: Basic TCP connection
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host_ip, port))
        sock.close()
        results["tests"]["tcp_connection"] = "PASS"
    except Exception as e:
        results["tests"]["tcp_connection"] = f"FAIL: {e}"

    # Test 2: HTTP request to /json
    try:
        import httpx

        response = httpx.get(f"http://{host_ip}:{port}/json", timeout=5)
        results["tests"]["http_json"] = f"Status {response.status_code}"
        if response.status_code == 200:
            data = response.json()
            results["tests"]["chrome_pages"] = len(data)
    except Exception as e:
        results["tests"]["http_json"] = f"FAIL: {e}"

    # Test 3: Check Chrome process on Windows
    ps_path = _get_powershell_path()
    if ps_path:
        try:
            ps_cmd = "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object -First 1"
            result = subprocess.run(
                [str(ps_path), "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
            )
            results["tests"]["chrome_running"] = (
                "YES" if "chrome" in result.stdout.lower() else "NO"
            )
        except Exception as e:
            results["tests"]["chrome_running"] = f"ERROR: {e}"

    # Test 4: Firewall rule
    results["tests"]["firewall_rule"] = "EXISTS" if check_firewall_rule(port) else "MISSING"

    # Test 5: Port binding on Windows
    if ps_path:
        try:
            ps_cmd = f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, State"
            result = subprocess.run(
                [str(ps_path), "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=10,
            )
            results["tests"]["port_binding"] = (
                result.stdout.strip() if result.stdout.strip() else "NOT_FOUND"
            )
        except Exception as e:
            results["tests"]["port_binding"] = f"ERROR: {e}"

    return results
