"""Utility functions for NotebookLM API client."""

import json
import urllib.parse
from datetime import UTC, datetime
from typing import Any

# RPC ID to method name mapping for debug logging
RPC_NAMES = {
    "wXbhsf": "list_notebooks",
    "rLM1Ne": "get_notebook",
    "CCqFvf": "create_notebook",
    "s0tc2d": "rename_notebook",
    "WWINqb": "delete_notebook",
    "izAoDd": "add_source",
    "hizoJc": "get_source",
    "yR9Yof": "check_freshness",
    "FLmJqe": "sync_drive",
    "tGMBJ": "delete_source",
    "b7Wfje": "rename_source",
    "hPTbtc": "get_conversations",
    "J7Gthc": "delete_chat_history",
    "hT54vc": "preferences",
    "ozz5Z": "add_source_v2",
    "ZwVcOc": "settings",
    "VfAZjd": "get_summary",
    "tr032e": "get_source_guide",
    "Ljjv0c": "start_fast_research",
    "QA9ei": "start_deep_research",
    "e3bVqc": "poll_research",
    "LBwxtb": "import_research",
    "R7cb6c": "create_studio",
    "gArtLc": "poll_studio",
    "V5N4be": "delete_studio",
    "v9rmvd": "get_interactive_html",
    "yyryJe": "generate_mind_map",
    "CYK0Xb": "save_mind_map",
    "cFji9": "list_mind_maps",
    "AH0mwd": "delete_mind_map",
    "QDyure": "share_notebook",
    "JFMDGd": "get_share_status",
    "KmcKPe": "revise_slide_deck",
    "agX4Bc": "label_manage",
    "le8sX": "label_mutate",
    "GyzE7e": "label_delete",
}


def _format_debug_json(data: Any, max_length: int = 2000) -> str:
    """Format data as pretty-printed JSON for debug logging."""
    try:
        formatted = json.dumps(data, indent=2, ensure_ascii=False)
        if len(formatted) > max_length:
            return formatted[:max_length] + "\n  ... (truncated)"
        return formatted
    except (TypeError, ValueError):
        result = str(data)
        if len(result) > max_length:
            return result[:max_length] + "... (truncated)"
        return result


def _decode_request_body(body: str) -> dict[str, Any]:
    """Decode URL-encoded request body and parse JSON structures."""
    result = {}
    try:
        parsed = urllib.parse.parse_qs(body.rstrip("&"))
        if "f.req" in parsed:
            f_req_raw = parsed["f.req"][0]
            try:
                f_req = json.loads(f_req_raw)
                result["f.req"] = f_req
                if isinstance(f_req, list) and len(f_req) > 0:
                    inner = f_req[0]
                    if isinstance(inner, list) and len(inner) > 0:
                        rpc_call = inner[0]
                        if isinstance(rpc_call, list) and len(rpc_call) >= 2:
                            result["rpc_id"] = rpc_call[0]
                            params_str = rpc_call[1]
                            if isinstance(params_str, str):
                                try:
                                    result["params"] = json.loads(params_str)
                                except json.JSONDecodeError:
                                    result["params"] = params_str
            except json.JSONDecodeError:
                result["f.req"] = f_req_raw
        if "at" in parsed:
            result["at"] = "(csrf_token)"
    except Exception:
        result["raw"] = body[:500] if len(body) > 500 else body
    return result


def _parse_url_params(url: str) -> dict[str, Any]:
    """Parse URL query parameters for debug display."""
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        return {k: v[0] if len(v) == 1 else v for k, v in params.items()}
    except Exception:
        return {}


def parse_timestamp(ts_array: list | None) -> str | None:
    """Convert [seconds, nanoseconds] timestamp array to ISO format string."""
    if not ts_array or not isinstance(ts_array, list) or len(ts_array) < 1:
        return None
    try:
        seconds = ts_array[0]
        if not isinstance(seconds, (int, float)):
            return None
        dt = datetime.fromtimestamp(seconds, tz=UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, OverflowError):
        return None


def extract_cookies_from_chrome_export(cookie_data: str | list[dict]) -> dict[str, str]:
    """Extract cookies from Chrome export format (JSON) or header string."""
    from notebooklm_tools.utils.browser import flatten_cookies

    if isinstance(cookie_data, list):
        # Chrome export carries domains; prefer .google.com on name collisions.
        return flatten_cookies(cookie_data)
    if not isinstance(cookie_data, str):
        return {}
    try:
        data = json.loads(cookie_data)
        if isinstance(data, list):
            return flatten_cookies(data)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        pass
    cookies = {}
    for item in cookie_data.split(";"):
        if "=" in item:
            name, value = item.strip().split("=", 1)
            name = name.strip()
            if name:
                cookies[name] = value
    return cookies
