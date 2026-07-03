from notebooklm_tools.core.utils import (
    RPC_NAMES,
    extract_cookies_from_chrome_export,
    parse_timestamp,
)


def test_parse_timestamp_valid():
    result = parse_timestamp([1700000000, 0])
    assert result == "2023-11-14T22:13:20Z"


def test_parse_timestamp_none():
    assert parse_timestamp(None) is None


def test_extract_cookies_header_string():
    result = extract_cookies_from_chrome_export("name=value; other=foo")
    assert result == {"name": "value", "other": "foo"}


def test_extract_cookies_from_chrome_export_list_prefers_google_com():
    """Bug 1: the NOTEBOOKLM_COOKIES env / Chrome-export path must pick the
    .google.com value on cross-domain name collisions, not whichever is last."""
    export = [
        {"name": "SID", "value": "vn", "domain": ".google.com.vn"},
        {"name": "SID", "value": "goog", "domain": ".google.com"},
        {"name": "SID", "value": "yt", "domain": ".youtube.com"},  # last
    ]
    assert extract_cookies_from_chrome_export(export)["SID"] == "goog"


def test_extract_cookies_from_chrome_export_json_list_prefers_google_com():
    import json as _json

    export = _json.dumps(
        [
            {"name": "HSID", "value": "yt", "domain": ".youtube.com"},
            {"name": "HSID", "value": "goog", "domain": ".google.com"},
        ]
    )
    assert extract_cookies_from_chrome_export(export)["HSID"] == "goog"


def test_rpc_names_exists():
    assert "wXbhsf" in RPC_NAMES
