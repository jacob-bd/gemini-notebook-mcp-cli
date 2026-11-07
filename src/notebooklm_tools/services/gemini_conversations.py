"""Experimental Gemini notebook conversation discovery using the selected NotebookLM session.

This is *not* an official Google API. Only observed read-only Gemini web RPCs
(HcT8bb and MaZiqc) are used. No session values are stored or logged.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from typing import Any

from notebooklm_tools.services import notebooks as notebooks_service
from notebooklm_tools.services.errors import ServiceError, ValidationError

NOTEBOOK_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
CONVERSATION_ID_RE = re.compile(r"^c_[A-Za-z0-9_-]{6,128}$")
NATIVE_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

BOOTSTRAP_URL = "https://gemini.google.com/app"
RPC_URL_TEMPLATE = "https://gemini.google.com/u/{account}/_/BardChatUi/data/batchexecute"
RPC_CONVERSATIONS = "MaZiqc"
RPC_NOTEBOOK_METADATA = "HcT8bb"
MAX_HTTP_RESPONSE_CHARS = 2_000_000
MAX_CONVERSATIONS = 10
MAX_TITLE_CHARS = 200
ACCOUNT_BINDINGS_ENV = "NOTEBOOKLM_GEMINI_ACCOUNT_BINDINGS"


class GeminiContinuityError(ServiceError):
    """A safe, user-facing error with no auth/session/response payload details."""


def _verify_account_binding(client: Any, account_index: int) -> str:
    """Require an explicit profile -> Gemini account index binding.

    Notebook source overlap proves shared notebook access, not that a different
    Google account does not have access to the same shared notebook.
    """
    profile = getattr(client, "_profile_name", None)
    if not isinstance(profile, str) or not profile.strip():
        raise GeminiContinuityError("Gemini requires a selected named NotebookLM profile")
    raw = os.environ.get(ACCOUNT_BINDINGS_ENV, "")
    if not raw:
        raise GeminiContinuityError("Gemini account binding is not configured")
    try:
        mapping = json.loads(raw)
    except ValueError as exc:
        raise GeminiContinuityError("Gemini account binding configuration is invalid") from exc
    if not isinstance(mapping, dict):
        raise GeminiContinuityError("Gemini account binding configuration is invalid")
    bound = mapping.get(profile)
    if type(bound) is not int or not 0 <= bound <= 9:
        raise GeminiContinuityError(
            "Selected NotebookLM profile has no valid Gemini account binding"
        )
    if bound != account_index:
        raise GeminiContinuityError(
            "Gemini account index does not match the selected profile binding"
        )
    return profile


def _require_http_logging_safe() -> None:
    """Fail closed when transport diagnostics might log session-bearing URLs.

    Dynamic filters alone cannot protect descendant loggers or other threads
    when verbose HTTP logging is enabled by the MCP host.
    """
    sources = (
        "httpx",
        "httpx._client",
        "httpcore",
        "httpcore._sync",
        "httpcore._sync.connection",
        "httpcore._sync.http11",
        "httpcore._sync.http2",
    )
    if any(logging.getLogger(name).isEnabledFor(logging.INFO) for name in sources):
        raise GeminiContinuityError(
            "Gemini requests are unavailable while verbose HTTP diagnostics are enabled"
        )


class _SuppressGeminiHttpLogging(logging.Filter):
    """Redact Gemini URLs, especially f.sid, from httpx/httpcore diagnostics."""

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        if "gemini.google.com" in rendered:
            record.msg = "Gemini HTTPS request (URL and session fields redacted)"
            record.args = ()
        return True


@contextmanager
def _guard_http_logs():
    # httpx logs the URL, which includes a session-scoped f.sid. Protect even
    # at INFO/DEBUG; do not globally change logging levels or credentials.
    names = (
        "httpx",
        "httpx._client",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
    )
    filter_obj = _SuppressGeminiHttpLogging()
    loggers = [logging.getLogger(name) for name in names]
    for logger in loggers:
        logger.addFilter(filter_obj)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeFilter(filter_obj)


def _extract_bootstrap(html: str) -> dict[str, str]:
    """Extract Gemini's fresh web-session values, in memory only."""
    if not isinstance(html, str) or not html:
        raise GeminiContinuityError("Gemini session bootstrap is unavailable")
    values = {}
    for field in ("SNlM0e", "cfb2h", "FdrFJe"):
        match = re.search(r'"' + re.escape(field) + r'"\s*:\s*("(?:[^"\\]|\\.)*")', html)
        if not match:
            raise GeminiContinuityError("Gemini session bootstrap schema changed")
        try:
            value = json.loads(match.group(1))
        except (TypeError, ValueError) as exc:
            raise GeminiContinuityError("Gemini session bootstrap schema changed") from exc
        if not isinstance(value, str) or not 2 <= len(value) <= 4096:
            raise GeminiContinuityError("Gemini session bootstrap value is invalid")
        values[field] = value
    return values


def _walk_lists(value: Any, depth: int = 0):
    if depth > 14:
        return
    if isinstance(value, list):
        yield value
        for child in value:
            yield from _walk_lists(child, depth + 1)


def _decode_rpc(text: str, rpc_id: str) -> Any:
    if not isinstance(text, str) or len(text) > MAX_HTTP_RESPONSE_CHARS:
        raise GeminiContinuityError("Unexpected Gemini RPC response size")
    candidates: list[Any] = []
    for line in text.splitlines():
        if not line.startswith("[["):
            continue
        try:
            envelope = json.loads(line)
        except (ValueError, TypeError) as exc:
            raise GeminiContinuityError("Gemini RPC frame is invalid") from exc
        for node in _walk_lists(envelope):
            if len(node) >= 3 and node[0] == "wrb.fr" and node[1] == rpc_id:
                try:
                    payload = json.loads(node[2]) if isinstance(node[2], str) else node[2]
                except (ValueError, TypeError) as exc:
                    raise GeminiContinuityError("Gemini RPC payload is invalid") from exc
                candidates.append(payload)
    if len(candidates) != 1:
        raise GeminiContinuityError("Gemini RPC response is missing or ambiguous")
    return candidates[0]


def _parse_native_source_overlap(payload: Any, notebook_id: str, native_ids: set[str]) -> int:
    """Fail closed unless Gemini's view matches the specific native notebook."""
    ref = "notebooks/" + notebook_id
    if not (
        isinstance(payload, list)
        and len(payload) == 1
        and isinstance(payload[0], list)
        and len(payload[0]) >= 2
        and payload[0][0] == ref
    ):
        raise GeminiContinuityError("Gemini returned a different notebook")
    try:
        source_rows = payload[0][1][10][0]
    except (IndexError, TypeError, KeyError) as exc:
        raise GeminiContinuityError("Gemini notebook metadata schema changed") from exc
    if not isinstance(source_rows, list):
        raise GeminiContinuityError("Gemini source metadata schema changed")
    gemini_sources: set[str] = set()
    for row in source_rows:
        if not (isinstance(row, list) and len(row) >= 6 and isinstance(row[5], str)):
            continue
        found = NATIVE_UUID_RE.findall(row[5])
        if found:
            gemini_sources.add(found[-1].lower())
    overlap = native_ids.intersection(gemini_sources)
    if not overlap:
        raise GeminiContinuityError(
            "Could not verify that Gemini and NotebookLM reference the same source inventory"
        )
    return len(overlap)


def _parse_conversations(payload: Any, notebook_id: str, limit: int) -> dict[str, Any]:
    """Return only notebook-bound Gemini conversation IDs and bounded titles."""
    if not (isinstance(payload, list) and len(payload) >= 3 and isinstance(payload[2], list)):
        raise GeminiContinuityError("Gemini conversation response schema changed")
    ref = "notebooks/" + notebook_id
    all_rows = payload[2]
    conversations = []
    seen = set()
    other_notebook_rows = 0
    invalid_rows = 0
    for row in all_rows:
        if not (isinstance(row, list) and len(row) >= 8 and isinstance(row[7], str)):
            invalid_rows += 1
            continue
        if row[7] != ref:
            other_notebook_rows += 1
            continue
        cid, title = row[0], row[1]
        if (
            not isinstance(cid, str)
            or not CONVERSATION_ID_RE.fullmatch(cid)
            or not isinstance(title, str)
        ):
            invalid_rows += 1
            continue
        if cid in seen:
            continue
        seen.add(cid)
        conversations.append(
            {
                "gemini_conversation_id": cid,
                "title": title.strip()[:MAX_TITLE_CHARS],
                "provenance": "gemini_notebook_scoped_conversation",
            }
        )
    return {
        "conversations": conversations[:limit],
        "returned_count": min(len(conversations), limit),
        "captured_conversation_count": len(conversations),
        "skipped_other_notebook_rows": other_notebook_rows,
        "skipped_malformed_rows": invalid_rows,
        "truncated": len(conversations) > limit,
        "complete_history": False,
    }


def _send_readonly_rpc(
    http: Any, account_index: int, bootstrap: dict[str, str], rpc: str, params: list[Any]
) -> Any:
    payload = json.dumps(
        [[[rpc, json.dumps(params, separators=(",", ":")), None, "generic"]]], separators=(",", ":")
    )
    query = {
        "rpcids": rpc,
        "source-path": "/app",
        "bl": bootstrap["cfb2h"],
        "f.sid": bootstrap["FdrFJe"],
        "hl": "en",
        "_reqid": "100000",
        "rt": "c",
    }
    form = {"f.req": payload, "at": bootstrap["SNlM0e"]}
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "X-Same-Domain": "1",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/app",
    }
    url = RPC_URL_TEMPLATE.format(account=account_index)
    with _guard_http_logs():
        try:
            response = http.post(
                url, params=query, data=form, headers=headers, timeout=30, follow_redirects=False
            )
        except Exception as exc:
            raise GeminiContinuityError("Gemini read-only request failed") from exc
    if response.status_code in (401, 403) or 300 <= response.status_code < 400:
        raise GeminiContinuityError(
            "Gemini session unavailable for the selected account; use visible login"
        )
    if response.status_code != 200:
        raise GeminiContinuityError("Gemini read-only request returned an error")
    return _decode_rpc(response.text, rpc)


def list_gemini_notebook_conversations(
    notebooklm_client: Any,
    notebook_id: str,
    *,
    limit: int = 10,
    gemini_account_index: int = 0,
) -> dict[str, Any]:
    """List Gemini conversations scoped to one NotebookLM notebook, read only.

    Selects a single explicitly indexed Gemini account. No fallback, account
    scan, cookies export, credential storage, background login, or mutations.
    """
    if not isinstance(notebook_id, str) or not NOTEBOOK_ID_RE.fullmatch(notebook_id):
        raise ValidationError("notebook_id must be a native notebook UUID")
    if type(limit) is not int or not 1 <= limit <= MAX_CONVERSATIONS:
        raise ValidationError("limit must be between 1 and 10")
    if type(gemini_account_index) is not int or not 0 <= gemini_account_index <= 9:
        raise ValidationError("gemini_account_index must be an integer between 0 and 9")
    notebook_id = notebook_id.lower()
    selected_profile = _verify_account_binding(notebooklm_client, gemini_account_index)
    _require_http_logging_safe()
    try:
        native = notebooks_service.get_notebook(notebooklm_client, notebook_id)
    except Exception as exc:
        raise GeminiContinuityError(
            "Notebook is inaccessible through the selected NotebookLM profile"
        ) from exc
    native_source_ids = {
        source["id"].lower()
        for source in native.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    if not native_source_ids:
        raise GeminiContinuityError(
            "Cannot verify Gemini account context for a notebook without native sources"
        )
    try:
        http = notebooklm_client._get_client()
        with _guard_http_logs():
            page = http.get(BOOTSTRAP_URL, timeout=25, follow_redirects=False)
    except Exception as exc:
        raise GeminiContinuityError("Gemini session bootstrap request failed") from exc
    if page.status_code != 200:
        raise GeminiContinuityError("Gemini session bootstrap is unavailable; use visible login")
    bootstrap = _extract_bootstrap(page.text)
    metadata = _send_readonly_rpc(
        http, gemini_account_index, bootstrap, RPC_NOTEBOOK_METADATA, ["notebooks/" + notebook_id]
    )
    matched_sources = _parse_native_source_overlap(metadata, notebook_id, native_source_ids)
    conversations_payload = _send_readonly_rpc(
        http,
        gemini_account_index,
        bootstrap,
        RPC_CONVERSATIONS,
        [10, None, [None, None, 1, "notebooks/" + notebook_id, 1]],
    )
    listed = _parse_conversations(conversations_payload, notebook_id, limit)
    return {
        "notebook_id": notebook_id,
        "notebook_title": str(native.get("title") or "")[:MAX_TITLE_CHARS],
        "gemini_account_index": gemini_account_index,
        "selected_notebooklm_profile": selected_profile,
        "account_binding": "explicit_profile_to_gemini_index",
        "identity_check": "native_source_uuid_overlap",
        "verified_native_source_ids": matched_sources,
        "native_notebook_source_count": len(native_source_ids),
        "read_only": True,
        "authentication": "selected_notebooklm_google_session",
        "conversation_namespace": "gemini",
        "notebooklm_chat_equivalence": "not_established",
        **listed,
    }
