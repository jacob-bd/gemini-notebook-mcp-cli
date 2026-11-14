"""Browser cookie utilities."""

import json
import re
from pathlib import Path
from typing import Any

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
    - cURL command (copy as cURL from DevTools), including inline cookies
      passed with -b/--cookie
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
            rows = [
                item
                for item in data
                if isinstance(item, dict) and "name" in item and "value" in item
            ]
            cookies = flatten_cookies(rows)
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

    # Try to extract from a cURL command (Cookie header or -b/--cookie value)
    content = _extract_cookie_argument_from_curl(content)

    # Try to extract Cookie header value
    if content.lower().startswith("cookie:"):
        content = content[7:].strip()

    # Parse cookie string (name=value; name2=value2)
    cookies: dict[str, str] = {}
    for part in content.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if not name or not value:
            continue
        if not _COOKIE_NAME_RE.match(name):
            raise AuthenticationError(
                message="Could not parse cookies from file",
                hint=(
                    "Found content that is not a cookie name. Use a Cookie header "
                    "value, a cURL command, JSON, or a Netscape cookie file."
                ),
            )
        cookies[name] = value

    if not cookies:
        raise AuthenticationError(
            message="Could not parse cookies from file",
            hint=(
                "The file should contain a Cookie header value, a cURL command "
                "(including -b/--cookie), JSON, or a Netscape cookie file."
            ),
        )

    return cookies


_CURL_COOKIE_HEADER_RE = re.compile(
    r"-H\s+\$?['\"]Cookie:\s*(?P<value>[^'\"\r\n]+)['\"]", re.IGNORECASE
)
_CURL_COOKIE_FLAG_RE = re.compile(
    r"(?:^|\s)(?:-b|--cookie)(?:\s+|=)\$?(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)
_CURL_COOKIE_FLAG_BARE_RE = re.compile(r"(?:^|\s)(?:-b|--cookie)(?:\s+|=)(?P<value>[^\s'\"]+)")
_COOKIE_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def _extract_cookie_argument_from_curl(content: str) -> str:
    """Return the cookie string carried by a cURL export, if there is one.

    Chrome's "Copy as cURL" exports carry cookies either in a Cookie header
    (-H 'Cookie: ...') or in the inline cookie option (-b 'name=value; ...').
    Inputs that are not cURL commands are returned unchanged.
    """
    header = _CURL_COOKIE_HEADER_RE.search(content)
    if header:
        return header.group("value")
    flag = _CURL_COOKIE_FLAG_RE.search(content) or _CURL_COOKIE_FLAG_BARE_RE.search(content)
    if flag:
        value = flag.group("value").strip()
        if "=" not in value.split(";", 1)[0]:
            raise AuthenticationError(
                message="Could not parse cookies from cURL input",
                hint=(
                    "-b/--cookie points at a cookie file. Paste the Cookie header "
                    "value instead, or pass the cookie file itself."
                ),
            )
        return value
    return content


def _try_parse_netscape_cookies(content: str) -> dict[str, str] | None:
    """
    Try to parse Netscape/Mozilla cookie file format.

    Format is tab-separated:
        domain  flag  path  secure  expires  name  value

    Lines starting with '#' are comments, except '#HttpOnly_' which marks
    an HttpOnly cookie. Returns None if the content doesn't appear to be
    Netscape format.
    """
    rows: list[dict[str, Any]] = []

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
                rows.append({"name": name, "value": value, "domain": parts[0].strip()})

    return flatten_cookies(rows) if rows else None


def flatten_cookies(cookies: dict[str, str] | list[dict[str, Any]]) -> dict[str, str]:
    """Flatten cookies to a dict, preferring exact ``.google.com`` values.

    Chrome can export the same auth cookie names for multiple Google-owned
    domains. NotebookLM runs on ``.google.com``, so those values should win when
    a name appears more than once.
    """
    if isinstance(cookies, dict):
        return cookies

    out: dict[str, str] = {}
    google_locked: set[str] = set()
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None:
            continue
        normalized_name = str(name)
        is_google = (cookie.get("domain") or "").lstrip(".").lower() == "google.com"
        if normalized_name in google_locked and not is_google:
            continue
        out[normalized_name] = str(value)
        if is_google:
            google_locked.add(normalized_name)
    return out


def cookies_to_header(cookies: dict[str, str]) -> str:
    """Convert cookies dict to Cookie header value."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def validate_notebooklm_cookies(cookies: dict[str, str] | list[dict[str, Any]]) -> bool:
    """
    Check if cookies appear to be valid for NotebookLM.

    This is a basic check - actual validation requires making an API call.
    """
    cookies = flatten_cookies(cookies)
    # Check for essential Google auth cookies
    essential_patterns = ["SID", "HSID", "SSID", "APISID", "SAPISID"]
    found = sum(1 for pattern in essential_patterns if any(pattern in name for name in cookies))
    return found >= 2  # At least 2 essential cookies should be present
