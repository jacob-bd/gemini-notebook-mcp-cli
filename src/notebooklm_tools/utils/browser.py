"""Browser cookie utilities."""

import json
import re
from pathlib import Path

from notebooklm_tools.core.exceptions import AuthenticationError
from notebooklm_tools.utils.config import get_base_url

# NotebookLM domain for cookie filtering
NOTEBOOKLM_DOMAIN = ".google.com"
NOTEBOOKLM_URL = get_base_url()


def parse_cookies_from_file(file_path: str | Path) -> dict[str, str]:
    """
    Parse cookies from a file.

    The file can contain:
    - Raw cookie header string (Cookie: name=value; name2=value2)
    - cURL command (copy as cURL from DevTools)
    - JSON object with cookies
    - Netscape/Mozilla cookie file format (tab-separated, as exported by
      browser extensions like "Get cookies.txt LOCALLY")

    Args:
        file_path: Path to the file containing cookies.

    Returns:
        Dictionary of cookie name -> value.

    Raises:
        AuthenticationError: If file cannot be parsed.
    """
    path = Path(file_path).expanduser()

    if not path.exists():
        raise AuthenticationError(
            message=f"Cookie file not found: {path}",
            hint="Create the file with cookies copied from browser DevTools.",
        )

    content = path.read_text(encoding="utf-8").strip("\r\n")

    # Try to parse as JSON first
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        if isinstance(data, list):
            # List of cookie objects
            cookies = {}
            for item in data:
                if isinstance(item, dict) and "name" in item and "value" in item:
                    cookies[item["name"]] = item["value"]
            if cookies:
                return cookies
    except json.JSONDecodeError:
        pass

    # Try Netscape/Mozilla cookie file format
    # Format: domain  flag  path  secure  expires  name  value  (tab-separated)
    # Lines starting with '#' are comments
    netscape_cookies = _try_parse_netscape_cookies(content)
    if netscape_cookies:
        return netscape_cookies

    # Try to extract from cURL command
    curl_match = re.search(r"-H\s+['\"]Cookie:\s*([^'\"]+)['\"]", content, re.IGNORECASE)
    if curl_match:
        content = curl_match.group(1)

    # Try to extract Cookie header value
    if content.lower().startswith("cookie:"):
        content = content[7:].strip()

    # Parse cookie string (name=value; name2=value2)
    cookies: dict[str, str] = {}
    for part in content.split(";"):
        part = part.strip()
        if "=" in part:
            name, _, value = part.partition("=")
            name = name.strip()
            value = value.strip()
            if name and value:
                cookies[name] = value

    if not cookies:
        raise AuthenticationError(
            message="Could not parse cookies from file",
            hint="The file should contain a Cookie header value or cURL command.",
        )

    return cookies


def _try_parse_netscape_cookies(content: str) -> dict[str, str] | None:
    """
    Try to parse Netscape/Mozilla cookie file format.

    Format is tab-separated:
        domain  flag  path  secure  expires  name  value

    Lines starting with '#' are comments, except '#HttpOnly_' which marks
    an HttpOnly cookie. Returns None if the content doesn't appear to be
    Netscape format.
    """
    cookies: dict[str, str] = {}
    valid_lines = 0

    for line in content.splitlines():
        # Keep trailing tabs so empty value cookies are not truncated by line.strip()
        line = line.rstrip("\r\n")
        stripped = line.strip()
        # Skip blank lines
        if not stripped:
            continue
        # Support #HttpOnly_ cookies (commonly written by exporters)
        if stripped.startswith("#HttpOnly_"):
            line = line.replace("#HttpOnly_", "", 1)
        elif stripped.startswith("#"):
            continue

        # Netscape format: 7 tab-separated fields
        parts = line.split("\t")
        if len(parts) >= 7:
            name = parts[5].strip()
            # Join remaining parts in case the value itself contains tabs
            value = "\t".join(parts[6:]).strip()
            if name:
                cookies[name] = value
                valid_lines += 1

    return cookies if valid_lines > 0 else None


def flatten_cookies(cookies: "list[dict] | dict[str, str]") -> dict[str, str]:
    """Flatten a cookie list to {name: value}, preferring the .google.com value.

    Chrome exports duplicate auth cookies (SID, HSID, SSID, APISID, ...) across
    .google.com, .youtube.com, .google.com.vn, etc. — often with *different*
    values per domain. A naive ``{c["name"]: c["value"] for c in cookies}`` lets
    whichever domain happens to be last in the list win, which can silently
    select another site's session token. NotebookLM lives on .google.com, so
    that domain always wins here; a non-google duplicate only fills a name no
    .google.com cookie has claimed.
    """
    if isinstance(cookies, dict):
        return cookies

    out: dict[str, str] = {}
    google_locked: set[str] = set()
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if not name or value is None:
            continue
        is_google = (c.get("domain") or "").lstrip(".") == "google.com"
        if name in google_locked and not is_google:
            continue  # keep the .google.com value already chosen
        out[name] = value
        if is_google:
            google_locked.add(name)
    return out


def cookies_to_header(cookies: dict[str, str]) -> str:
    """Convert cookies dict to Cookie header value."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def validate_notebooklm_cookies(cookies: "dict[str, str] | list[dict]") -> bool:
    """
    Check if cookies appear to be valid for NotebookLM.

    This is a basic check - actual validation requires making an API call.
    Accepts a flat dict or a Chrome-export list[dict].
    """
    cookies = flatten_cookies(cookies)
    # Check for essential Google auth cookies
    essential_patterns = ["SID", "HSID", "SSID", "APISID", "SAPISID"]
    found = sum(1 for pattern in essential_patterns if any(pattern in name for name in cookies))
    return found >= 2  # At least 2 essential cookies should be present
