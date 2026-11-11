"""Tests for cookie parsing from files (Netscape format support)."""

import json
import tempfile
from pathlib import Path

import pytest

from notebooklm_tools.core.exceptions import AuthenticationError
from notebooklm_tools.utils.browser import parse_cookies_from_file

# --- JSON format ---


def test_parse_json_dict():
    """JSON dict format: {"name": "value"}."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"SID": "abc123", "HSID": "def456"}, f)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"SID": "abc123", "HSID": "def456"}
    finally:
        Path(path).unlink(missing_ok=True)


# --- Netscape format ---

SAMPLE_NETSCAPE = """# Netscape HTTP Cookie File
# https://curl.haxx.se/rfc/cookie_spec.html
# This is a generated file! Do not edit.

.google.com\tTRUE\t/\tFALSE\t1788094158\tSEARCH_SAMESITE\tCgQIo6AB
.google.com\tTRUE\t/\tTRUE\t1788094158\t__Secure-BUCKET\tCMID
.google.com\tTRUE\t/\tFALSE\t1812953356\tSID\tsid-value-123
.google.com\tTRUE\t/\tTRUE\t1812953356\tHSID\tA1SAks--UQ
.google.com\tTRUE\t/\tTRUE\t1812953356\tSSID\tAYOTqrMe
.google.com\tTRUE\t/\tFALSE\t1812953356\tAPISID\tapi-value-789
.google.com\tTRUE\t/\tTRUE\t1812953356\tSAPISID\tsapi-value-000
notebooklm.google.com\tFALSE\t/\tTRUE\t1814162423\tOSID\tosid-value-111
"""


def test_parse_netscape_format():
    """Netscape cookie file with tab-separated fields."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(SAMPLE_NETSCAPE)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result["SID"] == "sid-value-123"
        assert result["HSID"] == "A1SAks--UQ"
        assert result["SSID"] == "AYOTqrMe"
        assert result["APISID"] == "api-value-789"
        assert result["SAPISID"] == "sapi-value-000"
        assert result["OSID"] == "osid-value-111"
        assert result["SEARCH_SAMESITE"] == "CgQIo6AB"
        assert result["__Secure-BUCKET"] == "CMID"
        assert len(result) == 8
    finally:
        Path(path).unlink(missing_ok=True)


def test_netscape_passes_validation():
    """Netscape cookies should pass validate_notebooklm_cookies."""
    from notebooklm_tools.utils.browser import validate_notebooklm_cookies

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(SAMPLE_NETSCAPE)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert validate_notebooklm_cookies(result) is True
    finally:
        Path(path).unlink(missing_ok=True)


def test_netscape_skips_blank_and_comments():
    """Blank lines and comments starting with # are skipped."""
    content = """# Header comment
# Another comment

.google.com\tTRUE\t/\tTRUE\t1\tMYCOOKIE\tmyvalue

"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"MYCOOKIE": "myvalue"}
    finally:
        Path(path).unlink(missing_ok=True)


def test_non_netscape_tab_content_ignored():
    """Content with tabs but not 7+ fields per line falls through."""
    content = "just\ta\tfew\tfields\nnot\tenough"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        with pytest.raises(AuthenticationError, match="Could not parse cookies"):
            parse_cookies_from_file(path)
    finally:
        Path(path).unlink(missing_ok=True)


# --- Cookie header format (existing, ensure not broken) ---


def test_parse_cookie_header():
    """Standard Cookie header format."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Cookie: SID=abc; HSID=def; SSID=ghi")
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"SID": "abc", "HSID": "def", "SSID": "ghi"}
    finally:
        Path(path).unlink(missing_ok=True)


def test_parse_name_value_pairs():
    """Plain name=value pairs separated by semicolons."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("SID=abc; HSID=def; SSID=ghi")
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"SID": "abc", "HSID": "def", "SSID": "ghi"}
    finally:
        Path(path).unlink(missing_ok=True)


def test_file_not_found():
    """Missing file raises AuthenticationError."""
    with pytest.raises(AuthenticationError, match="Cookie file not found"):
        parse_cookies_from_file("/tmp/nonexistent_cookie_file_xyz.txt")


# --- Edge cases for Netscape parser (HttpOnly, Empty Values, Values with Tabs) ---


def test_netscape_httponly_cookies():
    """Lines starting with '#HttpOnly_' should be parsed, not skipped as comments."""
    content = (
        "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1812953356\t__Secure-1PSIDTS\tsecure-value-123\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"__Secure-1PSIDTS": "secure-value-123"}
    finally:
        Path(path).unlink(missing_ok=True)


def test_netscape_mixed_httponly_and_regular():
    """Mix of regular lines and '#HttpOnly_' lines parses successfully."""
    content = (
        ".google.com\tTRUE\t/\tFALSE\t1812953356\tSID\tsid-value\n"
        "#HttpOnly_.google.com\tTRUE\t/\tTRUE\t1812953356\t__Secure-3PSIDTS\tsecure-value\n"
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"SID": "sid-value", "__Secure-3PSIDTS": "secure-value"}
    finally:
        Path(path).unlink(missing_ok=True)


def test_netscape_empty_value_cookie():
    """Cookies with empty values should be parsed with an empty string value."""
    content = ".google.com\tTRUE\t/\tFALSE\t1812953356\tEMPTY_COOKIE\t\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"EMPTY_COOKIE": ""}
    finally:
        Path(path).unlink(missing_ok=True)


def test_netscape_value_with_tabs():
    """Cookie values that contain tabs internally are joined and parsed fully."""
    content = ".google.com\tTRUE\t/\tFALSE\t1812953356\tTAB_COOKIE\tvalue\twith\ttabs\n"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(content)
        path = f.name
    try:
        result = parse_cookies_from_file(path)
        assert result == {"TAB_COOKIE": "value\twith\ttabs"}
    finally:
        Path(path).unlink(missing_ok=True)


# --- Chrome "Copy as cURL" exports (issue #403) ---


def _parse_cookie_text(text: str) -> dict[str, str]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        return parse_cookies_from_file(path)
    finally:
        Path(path).unlink(missing_ok=True)


def test_parse_curl_inline_cookie_flag():
    """Multiline Chrome export using -b 'name=value; ...' parses cleanly."""
    content = (
        "curl 'https://notebook.google.com/' \\\n"
        "  -b 'SID=fake-sid; HSID=fake-hsid' \\\n"
        "  -H 'accept: text/html'"
    )
    result = _parse_cookie_text(content)
    assert result == {"SID": "fake-sid", "HSID": "fake-hsid"}


def test_parse_curl_long_inline_cookie_flag():
    """The long --cookie form parses the same as -b."""
    content = "curl 'https://notebook.google.com/' --cookie 'SID=abc; HSID=def'"
    assert _parse_cookie_text(content) == {"SID": "abc", "HSID": "def"}


def test_parse_curl_cookie_flag_equals_form():
    """--cookie=value is a valid cURL form."""
    content = "curl 'https://notebook.google.com/' --cookie='SID=abc; HSID=def'"
    assert _parse_cookie_text(content) == {"SID": "abc", "HSID": "def"}


def test_parse_curl_cookie_file_reference_rejected():
    """-b pointing at a file must fail with an actionable error."""
    content = "curl 'https://notebook.google.com/' -b cookies.txt"
    with pytest.raises(AuthenticationError, match="cURL input"):
        _parse_cookie_text(content)


def test_malformed_cookie_name_rejected():
    """Unrecognized text must not become a garbage cookie key."""
    content = "some pasted text -H 'accept: text/html'"
    with pytest.raises(AuthenticationError, match="Could not parse cookies"):
        _parse_cookie_text(content)
