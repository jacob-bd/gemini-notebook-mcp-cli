#!/usr/bin/env python3
"""Base client infrastructure for NotebookLM API.

This module contains the BaseClient class which provides all HTTP/RPC
infrastructure for interacting with the NotebookLM internal API. Domain-specific
operations (notebooks, sources, studio, etc.) are provided by mixin classes.

Internal API. See CLAUDE.md for full documentation.
"""

import contextlib
import json
import logging
import os
import random
import re
import threading
import urllib.parse
from collections import OrderedDict
from typing import Any

import httpx

from notebooklm_tools.utils.config import get_base_url

from . import constants
from .data_types import ConversationTurn
from .errors import ClientAuthenticationError as AuthenticationError
from .errors import ResourceExhaustedError, RPCDriftError, RPCError, TransientBackendError
from .retry import (
    DEFAULT_BASE_DELAY,
    DEFAULT_MAX_DELAY,
    DEFAULT_MAX_RETRIES,
    RETRYABLE_CONNECT_ERRORS,
    is_retryable_error,
)
from .utils import (
    RPC_NAMES,
    _decode_request_body,
    _format_debug_json,
    _parse_url_params,
)

# Configure logger (API internals only logged at DEBUG level, usually disabled)
logger = logging.getLogger("notebooklm_mcp.api")
logger.setLevel(logging.WARNING)  # Suppress internal API logs by default


def _safe_int_env(name: str, default: int) -> int:
    """Read an integer env var, falling back to `default` if missing or unparseable.

    A value of 0 (or negative, clamped here) means "no cap" for cache-size knobs.
    Negative values are clamped to 0 and logged so a stray `-1` doesn't silently
    disable a cap the user thought they had set.
    """
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; falling back to default %d", name, raw, default)
        return default
    if value < 0:
        logger.warning("%s=%d is negative; clamping to 0 (no cap)", name, value)
        return 0
    return value


def _rate_limit_max_retries() -> int:
    """Return the retry ceiling for HTTP 429 and RPC RESOURCE_EXHAUSTED errors.

    The default preserves the standard transport retry behavior. Setting
    ``NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES=0`` surfaces rate limits immediately,
    which is useful when a caller or queue owns retry scheduling.
    """
    name = "NOTEBOOKLM_RATE_LIMIT_MAX_RETRIES"
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return DEFAULT_MAX_RETRIES
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; falling back to default %d",
            name,
            raw,
            DEFAULT_MAX_RETRIES,
        )
        return DEFAULT_MAX_RETRIES
    if value < 0:
        logger.warning("%s=%d is negative; clamping to 0", name, value)
        return 0
    return value


def load_rpc_overrides() -> dict[str, str]:
    """Load runtime RPC-ID overrides from NOTEBOOKLM_RPC_OVERRIDES.

    Lets users hot-patch rotated batchexecute method IDs without a release.
    The value is a JSON object mapping BaseClient RPC attribute names to new
    IDs, e.g. '{"RPC_LIST_NOTEBOOKS": "abc123"}'. Returns {} if unset, empty,
    or malformed (a warning is logged on malformed input).
    """
    raw = os.environ.get("NOTEBOOKLM_RPC_OVERRIDES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Ignoring malformed NOTEBOOKLM_RPC_OVERRIDES: %s", e)
        return {}
    if not isinstance(data, dict):
        logger.warning("Ignoring NOTEBOOKLM_RPC_OVERRIDES: expected a JSON object")
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _extract_user_message(detail_data: Any, _depth: int = 0) -> str:
    """Recursively extract human-readable strings from a protobuf detail payload.

    UserDisplayableError payloads contain user-facing text buried in nested
    lists. This walks the structure depth-first and returns all non-empty
    strings joined by '; '. Capped at 20 levels to guard against malformed
    responses.
    """
    if _depth > 20 or detail_data is None:
        return ""
    if isinstance(detail_data, str):
        stripped = detail_data.strip()
        return stripped if stripped else ""
    if isinstance(detail_data, list):
        parts: list[str] = []
        for item in detail_data:
            found = _extract_user_message(item, _depth + 1)
            if found:
                parts.append(found)
        return "; ".join(parts)
    return ""


# Timeout configuration (seconds)
DEFAULT_TIMEOUT = 30.0  # Default for most operations
SOURCE_ADD_TIMEOUT = 120.0  # Extended timeout for all source operations


def _is_unreachable_failure(exc: Exception | None) -> bool:
    """Return whether a refresh failure indicates an unreachable backend.

    A failed homepage refresh can mean either that credentials were rejected
    or that the request never reached a usable NotebookLM backend. Only the
    former should result in an authentication-expired message.
    """
    if exc is None:
        return False
    if isinstance(exc, (httpx.TransportError, httpx.TimeoutException, OSError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500

    text = str(exc).lower()
    if "accounts.google.com" in text or "authentication expired" in text or "expired" in text:
        return False
    if re.search(r"\b5\d{2}\b", text):
        return True
    return any(
        marker in text
        for marker in (
            "could not reach",
            "network",
            "timed out",
            "timeout",
            "connection",
            "temporarily unavailable",
            "dns",
        )
    )


class BaseClient:
    """Base client providing HTTP/RPC infrastructure for NotebookLM API.

    This class handles:
    - Authentication (cookies, CSRF tokens, session management)
    - HTTP client lifecycle
    - RPC request/response protocol (batchexecute)
    - Automatic authentication recovery

    Domain-specific operations are provided by mixin classes that inherit
    from this base class.
    """

    def _get_base_url(self) -> str:
        return get_base_url(getattr(self, "_base_host", "") or None)

    def _get_batchexecute_url(self) -> str:
        return f"{self._get_base_url()}/_/LabsTailwindUi/data/batchexecute"

    def _get_upload_url(self) -> str:
        return f"{self._get_base_url()}/upload/_/"

    # Keep class-level attributes for backward compatibility with code that
    # reads them directly (e.g. tests). These are the defaults; runtime code
    # should use the _get_*() methods which respect NOTEBOOKLM_BASE_URL.
    BASE_URL = "https://notebooklm.google.com"
    BATCHEXECUTE_URL = f"{BASE_URL}/_/LabsTailwindUi/data/batchexecute"
    UPLOAD_URL = "https://notebooklm.google.com/upload/_/"
    _BL_FALLBACK = "boq_labs-tailwind-frontend_20260108.06_p0"

    # =========================================================================
    # Known RPC IDs
    # =========================================================================

    # Notebook operations
    RPC_LIST_NOTEBOOKS = "wXbhsf"
    RPC_GET_NOTEBOOK = "rLM1Ne"
    RPC_CREATE_NOTEBOOK = "CCqFvf"
    RPC_RENAME_NOTEBOOK = "s0tc2d"
    RPC_DELETE_NOTEBOOK = "WWINqb"

    # Source operations
    RPC_ADD_SOURCE = "izAoDd"  # Used for URL, text, and Drive sources (legacy)
    RPC_ADD_SOURCE_V2 = "ozz5Z"  # URL source addition (new rollout, issue #121)
    RPC_ADD_SOURCE_FILE = "o4cbdc"  # Register file for resumable upload
    RPC_GET_SOURCE = "hizoJc"  # Get source details
    RPC_CHECK_FRESHNESS = "yR9Yof"  # Check if Drive source is stale
    RPC_SYNC_DRIVE = "FLmJqe"  # Sync Drive source with latest content
    RPC_DELETE_SOURCE = "tGMBJ"  # Delete a source from notebook
    RPC_RENAME_SOURCE = "b7Wfje"  # Rename a source

    # Misc
    RPC_GET_CONVERSATIONS = "hPTbtc"
    RPC_GET_CONVERSATION_TURNS = "khqZz"  # Fetch full Q&A turn history for a conversation ID
    RPC_DELETE_CHAT_HISTORY = "J7Gthc"
    RPC_PREFERENCES = "hT54vc"
    RPC_SETTINGS = "ZwVcOc"
    RPC_GET_SUMMARY = "VfAZjd"  # Get notebook summary and suggested report topics
    RPC_GET_SOURCE_GUIDE = "tr032e"  # Get source guide (AI summary + keyword chips)

    # Research RPCs (source discovery)
    RPC_START_FAST_RESEARCH = "Ljjv0c"  # Start Fast Research (Web or Drive)
    RPC_START_DEEP_RESEARCH = "QA9ei"  # Start Deep Research (Web only)
    RPC_POLL_RESEARCH = "e3bVqc"  # Poll research results
    RPC_IMPORT_RESEARCH = "LBwxtb"  # Import research sources

    # Studio content RPCs
    RPC_CREATE_STUDIO = "R7cb6c"  # Create Audio or Video Overview
    RPC_POLL_STUDIO = "gArtLc"  # Poll for studio content status
    RPC_DELETE_STUDIO = "V5N4be"  # Delete Audio or Video Overview
    RPC_RENAME_ARTIFACT = "rc3d8d"  # Rename any studio artifact (Audio, Video, etc.)
    RPC_GET_INTERACTIVE_HTML = "v9rmvd"  # Fetch quiz/flashcard HTML content
    RPC_REVISE_SLIDE_DECK = "KmcKPe"  # Revise existing slide deck with per-slide instructions

    # Mind map RPCs
    RPC_GENERATE_MIND_MAP = "yyryJe"  # Generate mind map JSON from sources
    RPC_SAVE_MIND_MAP = "CYK0Xb"  # Save generated mind map to notebook
    RPC_LIST_MIND_MAPS = "cFji9"  # List existing mind maps
    RPC_DELETE_MIND_MAP = "AH0mwd"  # Delete a mind map

    # Notes RPCs (share RPC IDs with mind maps, differ by parameters)
    RPC_CREATE_NOTE = "CYK0Xb"  # Create note from content (same as SAVE_MIND_MAP)
    RPC_GET_NOTES = "cFji9"  # List notes and mind maps (same as LIST_MIND_MAPS)
    RPC_UPDATE_NOTE = "cYAfTb"  # Update note content/title
    RPC_DELETE_NOTE = "AH0mwd"  # Delete note permanently (same as DELETE_MIND_MAP)

    # Label RPCs (source organization)
    RPC_LABEL_MANAGE = "agX4Bc"  # Auto-label sources / create label / list labels
    RPC_LABEL_MUTATE = "le8sX"  # Rename label / set emoji / move source to label
    RPC_LABEL_DELETE = "GyzE7e"  # Delete one or more labels

    # Sharing RPCs
    RPC_SHARE_NOTEBOOK = "QDyure"  # Set sharing settings (visibility, collaborators)
    RPC_GET_SHARE_STATUS = "JFMDGd"  # Get current share status

    # Export RPCs
    RPC_EXPORT_ARTIFACT = "Krh3pd"  # Export to Google Docs/Sheets

    # =========================================================================
    # API Constants (re-exported from constants module)
    # =========================================================================

    # Ownership
    OWNERSHIP_MINE = constants.OWNERSHIP_MINE
    OWNERSHIP_SHARED = constants.OWNERSHIP_SHARED

    # Research
    RESEARCH_SOURCE_WEB = constants.RESEARCH_SOURCE_WEB
    RESEARCH_SOURCE_DRIVE = constants.RESEARCH_SOURCE_DRIVE
    RESEARCH_MODE_FAST = constants.RESEARCH_MODE_FAST
    RESEARCH_MODE_DEEP = constants.RESEARCH_MODE_DEEP
    RESULT_TYPE_WEB = constants.RESULT_TYPE_WEB
    RESULT_TYPE_GOOGLE_DOC = constants.RESULT_TYPE_GOOGLE_DOC
    RESULT_TYPE_GOOGLE_SLIDES = constants.RESULT_TYPE_GOOGLE_SLIDES
    RESULT_TYPE_DEEP_REPORT = constants.RESULT_TYPE_DEEP_REPORT
    RESULT_TYPE_GOOGLE_SHEETS = constants.RESULT_TYPE_GOOGLE_SHEETS

    # Studio content types
    STUDIO_TYPE_AUDIO = constants.STUDIO_TYPE_AUDIO
    STUDIO_TYPE_VIDEO = constants.STUDIO_TYPE_VIDEO
    STUDIO_TYPE_REPORT = constants.STUDIO_TYPE_REPORT
    STUDIO_TYPE_FLASHCARDS = constants.STUDIO_TYPE_FLASHCARDS
    STUDIO_TYPE_INFOGRAPHIC = constants.STUDIO_TYPE_INFOGRAPHIC
    STUDIO_TYPE_SLIDE_DECK = constants.STUDIO_TYPE_SLIDE_DECK
    STUDIO_TYPE_DATA_TABLE = constants.STUDIO_TYPE_DATA_TABLE

    # Audio formats and lengths
    AUDIO_FORMAT_DEEP_DIVE = constants.AUDIO_FORMAT_DEEP_DIVE
    AUDIO_FORMAT_BRIEF = constants.AUDIO_FORMAT_BRIEF
    AUDIO_FORMAT_CRITIQUE = constants.AUDIO_FORMAT_CRITIQUE
    AUDIO_FORMAT_DEBATE = constants.AUDIO_FORMAT_DEBATE
    AUDIO_LENGTH_SHORT = constants.AUDIO_LENGTH_SHORT
    AUDIO_LENGTH_DEFAULT = constants.AUDIO_LENGTH_DEFAULT
    AUDIO_LENGTH_LONG = constants.AUDIO_LENGTH_LONG

    # Video formats and styles
    VIDEO_FORMAT_EXPLAINER = constants.VIDEO_FORMAT_EXPLAINER
    VIDEO_FORMAT_BRIEF = constants.VIDEO_FORMAT_BRIEF
    VIDEO_STYLE_AUTO_SELECT = constants.VIDEO_STYLE_AUTO_SELECT
    VIDEO_STYLE_CUSTOM = constants.VIDEO_STYLE_CUSTOM
    VIDEO_STYLE_CLASSIC = constants.VIDEO_STYLE_CLASSIC
    VIDEO_STYLE_WHITEBOARD = constants.VIDEO_STYLE_WHITEBOARD
    VIDEO_STYLE_KAWAII = constants.VIDEO_STYLE_KAWAII
    VIDEO_STYLE_ANIME = constants.VIDEO_STYLE_ANIME
    VIDEO_STYLE_WATERCOLOR = constants.VIDEO_STYLE_WATERCOLOR
    VIDEO_STYLE_RETRO_PRINT = constants.VIDEO_STYLE_RETRO_PRINT
    VIDEO_STYLE_HERITAGE = constants.VIDEO_STYLE_HERITAGE
    VIDEO_STYLE_PAPER_CRAFT = constants.VIDEO_STYLE_PAPER_CRAFT

    # Report formats
    REPORT_FORMAT_BRIEFING_DOC = constants.REPORT_FORMAT_BRIEFING_DOC
    REPORT_FORMAT_STUDY_GUIDE = constants.REPORT_FORMAT_STUDY_GUIDE
    REPORT_FORMAT_BLOG_POST = constants.REPORT_FORMAT_BLOG_POST
    REPORT_FORMAT_CUSTOM = constants.REPORT_FORMAT_CUSTOM

    # Flashcard settings
    FLASHCARD_DIFFICULTY_EASY = constants.FLASHCARD_DIFFICULTY_EASY
    FLASHCARD_DIFFICULTY_MEDIUM = constants.FLASHCARD_DIFFICULTY_MEDIUM
    FLASHCARD_DIFFICULTY_HARD = constants.FLASHCARD_DIFFICULTY_HARD
    FLASHCARD_COUNT_DEFAULT = constants.FLASHCARD_COUNT_DEFAULT

    # Infographic settings
    INFOGRAPHIC_ORIENTATION_LANDSCAPE = constants.INFOGRAPHIC_ORIENTATION_LANDSCAPE
    INFOGRAPHIC_ORIENTATION_PORTRAIT = constants.INFOGRAPHIC_ORIENTATION_PORTRAIT
    INFOGRAPHIC_ORIENTATION_SQUARE = constants.INFOGRAPHIC_ORIENTATION_SQUARE
    INFOGRAPHIC_DETAIL_CONCISE = constants.INFOGRAPHIC_DETAIL_CONCISE
    INFOGRAPHIC_DETAIL_STANDARD = constants.INFOGRAPHIC_DETAIL_STANDARD
    INFOGRAPHIC_DETAIL_DETAILED = constants.INFOGRAPHIC_DETAIL_DETAILED

    # Slide deck settings
    SLIDE_DECK_FORMAT_DETAILED = constants.SLIDE_DECK_FORMAT_DETAILED
    SLIDE_DECK_FORMAT_PRESENTER = constants.SLIDE_DECK_FORMAT_PRESENTER
    SLIDE_DECK_LENGTH_SHORT = constants.SLIDE_DECK_LENGTH_SHORT
    SLIDE_DECK_LENGTH_DEFAULT = constants.SLIDE_DECK_LENGTH_DEFAULT

    # Chat configuration
    CHAT_GOAL_DEFAULT = constants.CHAT_GOAL_DEFAULT
    CHAT_GOAL_CUSTOM = constants.CHAT_GOAL_CUSTOM
    CHAT_GOAL_LEARNING_GUIDE = constants.CHAT_GOAL_LEARNING_GUIDE
    CHAT_RESPONSE_DEFAULT = constants.CHAT_RESPONSE_DEFAULT
    CHAT_RESPONSE_LONGER = constants.CHAT_RESPONSE_LONGER
    CHAT_RESPONSE_SHORTER = constants.CHAT_RESPONSE_SHORTER

    # Source types
    SOURCE_TYPE_GOOGLE_DOCS = constants.SOURCE_TYPE_GOOGLE_DOCS
    SOURCE_TYPE_GOOGLE_OTHER = constants.SOURCE_TYPE_GOOGLE_OTHER
    SOURCE_TYPE_PASTED_TEXT = constants.SOURCE_TYPE_PASTED_TEXT
    SOURCE_TYPE_AUDIO = constants.SOURCE_TYPE_AUDIO

    # Sharing
    SHARE_ROLE_OWNER = constants.SHARE_ROLE_OWNER
    SHARE_ROLE_EDITOR = constants.SHARE_ROLE_EDITOR
    SHARE_ROLE_VIEWER = constants.SHARE_ROLE_VIEWER
    SHARE_ACCESS_RESTRICTED = constants.SHARE_ACCESS_RESTRICTED
    SHARE_ACCESS_PUBLIC = constants.SHARE_ACCESS_PUBLIC

    # Export types
    EXPORT_TYPE_DOCS = constants.EXPORT_TYPE_DOCS
    EXPORT_TYPE_SHEETS = constants.EXPORT_TYPE_SHEETS

    # Query endpoint (different from batchexecute - streaming gRPC-style)
    QUERY_ENDPOINT = "/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed"

    # Headers required for page fetch (must look like a browser navigation).
    # We use a generic Linux Chrome UA and omit sec-ch-ua* Client Hints intentionally:
    # those headers embed OS/platform fingerprints (e.g. "macOS") that can cause Google
    # to reject requests when the session cookies were captured on a different OS (e.g.
    # Windows). Client Hints are optional — omitting them is safe and platform-neutral.
    _PAGE_FETCH_HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }

    # =========================================================================
    # Lifecycle Methods
    # =========================================================================

    def __init__(
        self,
        cookies: dict[str, str] | list[dict],
        csrf_token: str = "",
        session_id: str = "",
        build_label: str = "",
        base_host: str = "",
        profile_name: str | None = None,
    ):
        """
        Initialize the base client.

        Args:
            cookies: Dict of Google auth cookies or List of cookie dicts (from CDP)
            csrf_token: CSRF token (optional - will be auto-extracted from page if not provided)
            session_id: Session ID (optional - will be auto-extracted from page if not provided)
            build_label: Build label / bl param (optional - auto-extracted from page if not provided)
            base_host: Host the account is signed in on, e.g. "notebook.google.com"
                (optional - falls back to NOTEBOOKLM_BASE_URL or the default host)
            profile_name: Auth profile that owns these credentials. Uses the
                configured default when omitted.
        """
        import time as _time

        self.cookies = cookies
        self.csrf_token = csrf_token
        self._client: httpx.Client | None = None
        self._session_id = session_id
        self._bl = build_label
        self._base_host = base_host
        self._profile_name = profile_name
        self._created_at: float = _time.time()

        # Conversation cache for follow-up queries.
        # Key: conversation_id, Value: list of ConversationTurn objects.
        #
        # Bounded to prevent unbounded memory growth in long-lived MCP server
        # processes (Issue #213). The dict itself is an OrderedDict for LRU
        # eviction; per-conversation turn lists are FIFO-trimmed. See
        # `_cache_conversation_turn` for the actual caps and eviction logic.
        self._max_turns_per_conversation = _safe_int_env(
            "NOTEBOOKLM_CONVERSATION_MAX_TURNS", default=50
        )
        self._max_conversations = _safe_int_env("NOTEBOOKLM_CONVERSATION_MAX_CONVS", default=500)
        self._max_chars_per_turn = _safe_int_env(
            "NOTEBOOKLM_CONVERSATION_MAX_CHARS_PER_TURN", default=100_000
        )
        self._conversation_cache: OrderedDict[str, list[ConversationTurn]] = OrderedDict()

        # Request counter for _reqid parameter (required for query endpoint)
        self._reqid_counter = random.randint(100000, 999999)
        self._cdp_ws_url: str | None = None
        self._cdp_launched_port: int | None = None

        # RPC version cache for URL source addition (issue #121).
        # Google is rolling out a new RPC (ozz5Z) to replace izAoDd for URL sources.
        # This caches which version works for this session to avoid double HTTP calls.
        # Values: None (unresolved), "v1" (izAoDd), "v2" (ozz5Z)
        self._source_rpc_version: str | None = None

        # Lock for thread-safe access to mutable instance state.
        # FastMCP dispatches sync tool functions into a thread pool, so
        # concurrent MCP tool calls share this singleton client instance.
        # The lock protects: _client, _reqid_counter, _conversation_cache,
        # _source_rpc_version, csrf_token, _session_id, cookies.
        # It is never held during network I/O.
        self._state_lock = threading.Lock()

        # Apply any runtime RPC-ID overrides (hot-patch for rotated method IDs).
        self._apply_rpc_overrides()

        # Only refresh CSRF token if not provided - tokens actually last hours/days, not minutes
        # The retry logic in _call_rpc() handles expired tokens gracefully
        if not self.csrf_token:
            if self._cdp_rpc_transport_enabled():
                self._prepare_cdp_transport(DEFAULT_TIMEOUT)
            else:
                self._refresh_auth_tokens()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Close the underlying HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
        if self._cdp_launched_port is not None:
            from notebooklm_tools.utils import cdp

            with contextlib.suppress(Exception):
                cdp.terminate_chrome(port=self._cdp_launched_port)
            self._cdp_launched_port = None
            self._cdp_ws_url = None

    def _apply_rpc_overrides(self) -> None:
        """Apply NOTEBOOKLM_RPC_OVERRIDES as instance attributes.

        Each entry shadows the matching class-level RPC_* constant on this
        instance only. Unknown keys (not an existing RPC_* attribute) are
        logged and ignored so a typo can never silently disable a tool.
        """
        for name, new_id in load_rpc_overrides().items():
            if not name.startswith("RPC_") or not hasattr(type(self), name):
                logger.warning("Ignoring unknown RPC override: %s", name)
                continue
            old_id = getattr(type(self), name)
            setattr(self, name, new_id)
            # INFO, not WARNING: an applied override is an intentional, benign
            # event and should not pollute the warning stream.
            logger.info("RPC override applied: %s %s -> %s", name, old_id, new_id)

    # =========================================================================
    # Cookie Handling
    # =========================================================================

    def _get_httpx_cookies(self) -> httpx.Cookies:
        """Convert cookies to httpx.Cookies object (preserving domains).

        Duplicates cookies for both .google.com and .googleusercontent.com
        to ensure authentication works across redirect domains.
        """
        cookies = httpx.Cookies()

        # Determine if we have raw list[dict] or simple dict[str, str]
        if isinstance(self.cookies, list):
            for cookie in self.cookies:
                name = cookie.get("name")
                value = cookie.get("value")
                domain = cookie.get("domain")
                path = cookie.get("path", "/")

                if name and value:
                    # Set cookie for original domain
                    cookies.set(name, value, domain=domain, path=path)

                    # Also duplicate for .googleusercontent.com if original is .google.com
                    # This is required for artifact downloads that redirect to googleusercontent.com
                    if domain == ".google.com":
                        cookies.set(name, value, domain=".googleusercontent.com", path=path)
        else:
            # Fallback for simple dict - set for both domains
            for name, value in self.cookies.items():
                cookies.set(name, value, domain=".google.com")
                cookies.set(name, value, domain=".googleusercontent.com")

        return cookies

    def _get_cookie_header(self) -> str:
        """Get Cookie header string (backward compatibility)."""
        from notebooklm_tools.utils.browser import flatten_cookies

        simple_cookies = flatten_cookies(self.cookies)
        return "; ".join(f"{k}={v}" for k, v in simple_cookies.items())

    # =========================================================================
    # HTTP Client Management
    # =========================================================================

    def _get_client(self) -> httpx.Client:
        """Get or create HTTP client (thread-safe)."""
        if self._client is not None:
            return self._client
        with self._state_lock:
            # Double-checked locking: re-check inside lock
            if self._client is not None:
                return self._client
            # Use cookies object directly
            cookies = self._get_httpx_cookies()

            client = httpx.Client(
                cookies=cookies,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "Origin": self._get_base_url(),
                    "Referer": f"{self._get_base_url()}/",
                    "X-Same-Domain": "1",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                },
                timeout=30.0,
            )

            # Explicitly set headers if needed, though constructor handles most
            if self.csrf_token:
                client.headers["X-Goog-Csrf-Token"] = self.csrf_token

            self._client = client
        return self._client

    def _get_async_client(self) -> httpx.AsyncClient:
        """Get an async client for streaming operations."""
        cookies = self._get_httpx_cookies()

        client = httpx.AsyncClient(
            cookies=cookies,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Origin": self._get_base_url(),
                "Referer": f"{self._get_base_url()}/",
                "X-Same-Domain": "1",
            },
            timeout=30.0,
        )
        if self.csrf_token:
            client.headers["X-Goog-Csrf-Token"] = self.csrf_token
        return client

    # =========================================================================
    # RPC Request/Response Protocol
    # =========================================================================

    def _build_request_body(self, rpc_id: str, params: Any) -> str:
        """Build the batchexecute request body."""
        # The params need to be JSON-encoded, then wrapped in the RPC structure
        # Use separators to match Chrome's compact format (no spaces)
        params_json = json.dumps(params, separators=(",", ":"), ensure_ascii=False)

        f_req = [[[rpc_id, params_json, None, "generic"]]]
        f_req_json = json.dumps(f_req, separators=(",", ":"), ensure_ascii=False)

        # URL encode (safe='' encodes all characters including /)
        body_parts = [f"f.req={urllib.parse.quote(f_req_json, safe='')}"]

        if self.csrf_token:
            body_parts.append(f"at={urllib.parse.quote(self.csrf_token, safe='')}")

        # Add trailing & to match NotebookLM's format
        return "&".join(body_parts) + "&"

    def _build_url(self, rpc_id: str, source_path: str = "/") -> str:
        """Build the batchexecute URL with query params."""
        params = {
            "rpcids": rpc_id,
            "source-path": source_path,
            "bl": os.environ.get("NOTEBOOKLM_BL") or getattr(self, "_bl", "") or self._BL_FALLBACK,
            "hl": os.environ.get("NOTEBOOKLM_HL", "en"),
            "rt": "c",
        }

        if self._session_id:
            params["f.sid"] = self._session_id

        query = urllib.parse.urlencode(params)
        return f"{self._get_batchexecute_url()}?{query}"

    def _parse_response(self, response_text: str) -> Any:
        """Parse the batchexecute response."""
        # Response format:
        # )]}'
        # <byte_count>
        # <json_array>

        # Remove the anti-XSSI prefix
        if response_text.startswith(")]}'"):
            response_text = response_text[4:]

        lines = response_text.strip().split("\n")

        # Parse each chunk
        results = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # Try to parse as byte count (the value itself is unused — only used
            # to confirm the line is a numeric chunk-size marker)
            try:
                int(line)
                # Next line(s) should be the JSON payload
                i += 1
                if i < len(lines):
                    json_str = lines[i]
                    try:
                        data = json.loads(json_str)
                        results.append(data)
                    except json.JSONDecodeError:
                        pass
                i += 1
            except ValueError:
                # Not a byte count, try to parse as JSON
                try:
                    data = json.loads(line)
                    results.append(data)
                except json.JSONDecodeError:
                    pass
                i += 1

        return results

    def _extract_rpc_result(self, parsed_response: list, rpc_id: str) -> Any:
        """Extract the result for a specific RPC ID from the parsed response.

        Checks for structured error payloads in item[5]. Known error layout:
            ["wrb.fr", rpc_id, result_or_null, ..., error_list, "generic"]
        where error_list = [error_code, null, [[detail_type_url, [sub_codes...]]]]
        """
        for chunk in parsed_response:
            if isinstance(chunk, list):
                for item in chunk:
                    if isinstance(item, list) and len(item) >= 3:  # noqa: SIM102
                        if item[0] == "wrb.fr" and item[1] == rpc_id:
                            # Check for structured error in item[5]
                            if len(item) > 5 and isinstance(item[5], list) and item[5]:
                                error_code = item[5][0] if isinstance(item[5][0], int) else None

                                if error_code is not None:
                                    # Auth error (code 16) — existing behavior
                                    if error_code == 16:
                                        raise AuthenticationError(
                                            "RPC Error 16: Authentication expired"
                                        )

                                    # All other error codes — extract detail type
                                    detail_type = ""
                                    detail_data = None
                                    if len(item[5]) > 2 and isinstance(item[5][2], list):
                                        for detail in item[5][2]:
                                            if isinstance(detail, list) and len(detail) > 0:
                                                detail_type = (
                                                    detail[0] if isinstance(detail[0], str) else ""
                                                )
                                                detail_data = detail[1] if len(detail) > 1 else None
                                                break

                                    # Provide fallback names for common gRPC status codes
                                    # if the backend didn't provide a specific detail_type
                                    friendly_type = detail_type
                                    if not friendly_type:
                                        grpc_codes = {
                                            3: "INVALID_ARGUMENT",
                                            5: "NOT_FOUND",
                                            7: "PERMISSION_DENIED",
                                            8: "RESOURCE_EXHAUSTED",
                                            16: "UNAUTHENTICATED",
                                        }
                                        friendly_type = grpc_codes.get(error_code, "unknown")

                                    msg = f"API error (code {error_code}): {friendly_type}"

                                    if "UserDisplayableError" in detail_type:
                                        user_msg = _extract_user_message(detail_data)
                                        if user_msg:
                                            msg = f"API error (code {error_code}): {user_msg}"

                                    if error_code == 8:
                                        raise ResourceExhaustedError(
                                            msg,
                                            detail_type=detail_type,
                                            detail_data=detail_data,
                                        )

                                    raise RPCError(
                                        msg,
                                        error_code=error_code,
                                        detail_type=detail_type,
                                        detail_data=detail_data,
                                    )

                            result_str = item[2]
                            if isinstance(result_str, str):
                                try:
                                    return json.loads(result_str)
                                except json.JSONDecodeError:
                                    return result_str
                            return result_str
        present = self._extract_present_rpc_ids(parsed_response)
        if present and rpc_id not in present:
            raise RPCDriftError(rpc_id, present)
        return None

    def _extract_present_rpc_ids(self, parsed_response: list) -> list[str]:
        """Return the rpc_ids of every wrb.fr chunk in a parsed response.

        Used for drift diagnostics: when the expected rpc_id is missing, this
        reveals which IDs the server actually returned so the user can set
        NOTEBOOKLM_RPC_OVERRIDES.
        """
        present: list[str] = []
        for chunk in parsed_response:
            if isinstance(chunk, list):
                for item in chunk:
                    if (
                        isinstance(item, list)
                        and len(item) >= 2
                        and item[0] == "wrb.fr"
                        and isinstance(item[1], str)
                    ):
                        present.append(item[1])
        return present

    def _cdp_rpc_transport_enabled(self) -> bool:
        from .cdp_transport import cdp_transport_enabled

        return cdp_transport_enabled()

    def _prepare_cdp_transport(self, timeout: float | None = None) -> None:
        """Refresh request tokens from a profile-owned NotebookLM browser page."""
        from .cdp_transport import get_cdp_page_context

        with self._state_lock:
            if self._cdp_ws_url and self._session_id:
                return
            csrf_fallback = self.csrf_token
            session_fallback = self._session_id
            build_fallback = self._bl

        context = get_cdp_page_context(
            profile_name=self._profile_name,
            timeout=timeout or DEFAULT_TIMEOUT,
            csrf_fallback=csrf_fallback,
            session_fallback=session_fallback,
            build_fallback=build_fallback,
        )
        with self._state_lock:
            self.csrf_token = context.csrf_token
            self._session_id = context.session_id
            self._bl = context.build_label
            self._cdp_ws_url = context.ws_url
            if context.launched:
                self._cdp_launched_port = context.port

    def _post_form_via_cdp(self, url: str, body: str, timeout: float | None = None) -> str:
        """POST an already-built form request through the browser page."""
        from .cdp_transport import CdpTransportError, fetch_form_in_page

        with self._state_lock:
            ws_url = self._cdp_ws_url

        if not ws_url:
            self._prepare_cdp_transport(timeout or DEFAULT_TIMEOUT)
            with self._state_lock:
                ws_url = self._cdp_ws_url

        if not ws_url:
            raise CdpTransportError("CDP transport was enabled, but no page websocket was found.")

        result = fetch_form_in_page(ws_url, url, body, timeout=timeout or DEFAULT_TIMEOUT)
        if result.status_code in (400, 401, 403):
            raise AuthenticationError(f"CDP fetch returned HTTP {result.status_code}.")
        if result.status_code >= 400:
            raise CdpTransportError(f"CDP fetch returned HTTP {result.status_code}.")
        return result.text

    def _call_rpc_via_cdp(
        self,
        rpc_id: str,
        params: Any,
        path: str = "/",
        timeout: float | None = None,
        _server_retry: int = 0,
    ) -> Any:
        """Execute a batchexecute RPC through the experimental CDP transport."""
        self._prepare_cdp_transport(timeout or DEFAULT_TIMEOUT)
        body = self._build_request_body(rpc_id, params)
        url = self._build_url(rpc_id, path)
        response_text = self._post_form_via_cdp(url, body, timeout or DEFAULT_TIMEOUT)

        parsed = self._parse_response(response_text)
        try:
            return self._extract_rpc_result(parsed, rpc_id)
        except ResourceExhaustedError:
            max_retries = _rate_limit_max_retries()
            if _server_retry < max_retries:
                import time as _time

                delay = min(DEFAULT_BASE_DELAY * (2**_server_retry), DEFAULT_MAX_DELAY)
                logger.warning(
                    "RPC rate limit (RESOURCE_EXHAUSTED) on %s, attempt %d/%d, retrying in %.1fs...",
                    rpc_id,
                    _server_retry + 1,
                    max_retries + 1,
                    delay,
                )
                _time.sleep(delay)
                return self._call_rpc_via_cdp(
                    rpc_id,
                    params,
                    path,
                    timeout,
                    _server_retry=_server_retry + 1,
                )
            raise

    def _call_rpc(
        self,
        rpc_id: str,
        params: Any,
        path: str = "/",
        timeout: float | None = None,
        _retry: bool = False,
        _deep_retry: bool = False,
        _server_retry: int = 0,
    ) -> Any:
        """Execute an RPC call and return the extracted result.

        Includes automatic retry on auth failures with three-layer recovery:
        1. Refresh CSRF/session tokens (fast, handles token expiry)
        2. Reload cookies from disk (handles external re-authentication)
        3. Run headless auth (auto-refresh if Chrome profile has saved login)
        """
        if self._cdp_rpc_transport_enabled():
            return self._call_rpc_via_cdp(
                rpc_id,
                params,
                path,
                timeout,
                _server_retry=_server_retry,
            )

        client = self._get_client()
        body = self._build_request_body(rpc_id, params)
        url = self._build_url(rpc_id, path)

        # Enhanced debug logging
        if logger.isEnabledFor(logging.DEBUG):
            method_name = RPC_NAMES.get(rpc_id, "unknown")
            logger.debug("=" * 70)
            logger.debug(f"RPC Call: {rpc_id} ({method_name})")
            logger.debug("-" * 70)

            # Parse and display URL params
            url_params = _parse_url_params(url)
            logger.debug("URL Parameters:")
            for key, value in url_params.items():
                logger.debug(f"  {key}: {value}")

            # Decode and display request body
            logger.debug("-" * 70)
            logger.debug("Request Params:")
            decoded_body = _decode_request_body(body)
            if "params" in decoded_body:
                logger.debug(_format_debug_json(decoded_body["params"]))
            elif "f.req" in decoded_body:
                logger.debug(_format_debug_json(decoded_body["f.req"]))
            else:
                logger.debug(_format_debug_json(decoded_body))

        try:
            if timeout:
                response = client.post(url, content=body, timeout=timeout)
            else:
                response = client.post(url, content=body)

            # Log response before raise_for_status (so we can see error responses)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("-" * 70)
                logger.debug(f"Response Status: {response.status_code}")
                logger.debug(
                    "Raw response (first 2000 chars): %s",
                    response.text[:2000] if response.text else "(empty)",
                )
                logger.debug("=" * 70)

            response.raise_for_status()

            # Check for RPC-level errors (soft auth failure)
            parsed = self._parse_response(response.text)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("RPC IDs in response: %s", self._extract_present_rpc_ids(parsed))
            result = self._extract_rpc_result(parsed, rpc_id)

            # Enhanced debug logging for extracted result
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("-" * 70)
                logger.debug("Response Data:")
                logger.debug(_format_debug_json(result))
                logger.debug("=" * 70)

            return result

        except httpx.HTTPStatusError as e:
            # Retry on transient server errors (5xx, 429) with exponential backoff.
            # Rate limits have a separate ceiling so external schedulers can own
            # retry policy without disabling safe connection or 5xx retries.
            if is_retryable_error(e):
                import time as _time

                status = e.response.status_code
                max_retries = _rate_limit_max_retries() if status == 429 else DEFAULT_MAX_RETRIES
                # Use _server_retry to track retries across recursive calls
                if _server_retry < max_retries:
                    delay = min(DEFAULT_BASE_DELAY * (2**_server_retry), DEFAULT_MAX_DELAY)
                    logger.warning(
                        f"Server error {status} on attempt {_server_retry + 1}/{max_retries + 1}, "
                        f"retrying in {delay:.1f}s..."
                    )
                    _time.sleep(delay)
                    return self._call_rpc(
                        rpc_id,
                        params,
                        path,
                        timeout,
                        _retry,
                        _deep_retry,
                        _server_retry=_server_retry + 1,
                    )
                # Exhausted retries, re-raise
                raise

            # Check for auth failures (400/401/403 HTTP)
            # 400 is included because Google returns "400 Bad Request" when
            # the CSRF token (at= body param) is expired or invalid, rather
            # than a 401/403.  Our Layer-1 recovery (_refresh_auth_tokens)
            # re-extracts a fresh CSRF token from the page, which fixes this.
            is_http_auth = e.response.status_code in (400, 401, 403)
            if not is_http_auth:
                # Not a retryable or auth error, re-raise immediately
                raise

            # Fall through to auth recovery below
            pass

        except RETRYABLE_CONNECT_ERRORS as e:
            # Connection never established → the server never received the
            # request, so retrying is always safe (even for mutating RPCs).
            # Read/write timeouts are intentionally excluded; see
            # retry.RETRYABLE_CONNECT_ERRORS.
            if _server_retry < DEFAULT_MAX_RETRIES:
                import time as _time

                delay = min(DEFAULT_BASE_DELAY * (2**_server_retry), DEFAULT_MAX_DELAY)
                logger.warning(
                    "Connection error (%s) on %s, attempt %d/%d, retrying in %.1fs...",
                    type(e).__name__,
                    rpc_id,
                    _server_retry + 1,
                    DEFAULT_MAX_RETRIES + 1,
                    delay,
                )
                _time.sleep(delay)
                return self._call_rpc(
                    rpc_id,
                    params,
                    path,
                    timeout,
                    _retry,
                    _deep_retry,
                    _server_retry=_server_retry + 1,
                )
            # Exhausted retries, re-raise
            raise

        except ResourceExhaustedError:
            # RPC-level rate limit (HTTP 200, error code 8). Back off and retry.
            max_retries = _rate_limit_max_retries()
            if _server_retry < max_retries:
                import time as _time

                delay = min(DEFAULT_BASE_DELAY * (2**_server_retry), DEFAULT_MAX_DELAY)
                logger.warning(
                    "RPC rate limit (RESOURCE_EXHAUSTED) on %s, attempt %d/%d, retrying in %.1fs...",
                    rpc_id,
                    _server_retry + 1,
                    max_retries + 1,
                    delay,
                )
                _time.sleep(delay)
                return self._call_rpc(
                    rpc_id,
                    params,
                    path,
                    timeout,
                    _retry,
                    _deep_retry,
                    _server_retry=_server_retry + 1,
                )
            raise

        except AuthenticationError:
            # RPC Error 16 - fall through to auth recovery below
            pass

        # -- Auth recovery (reached only for 401/403 HTTP or RPC Error 16) --

        # Layer 1: Refresh CSRF/session tokens (first retry only)
        if not _retry:
            try:
                self._refresh_auth_tokens()
                with self._state_lock:
                    self._client = None
                return self._call_rpc(rpc_id, params, path, timeout, _retry=True)
            except (ValueError, httpx.HTTPError, OSError) as exc:
                # A transport or 5xx failure is not evidence that credentials
                # expired. Retrying auth would produce the wrong user guidance
                # and may launch a needless interactive login.
                if _is_unreachable_failure(exc):
                    raise TransientBackendError(
                        "Could not reach NotebookLM while verifying the session.",
                        hint=(
                            "Check your connection and retry; your saved credentials may still "
                            "be valid."
                        ),
                    ) from exc
                # A redirect to accounts.google.com or an explicit expiry
                # message remains a genuine authentication failure.
                pass

        # Layer 2 & 3: Reload from disk or run headless auth (deep retry)
        if not _deep_retry and self._try_reload_or_headless_auth():
            with self._state_lock:
                self._client = None
            return self._call_rpc(rpc_id, params, path, timeout, _retry=True, _deep_retry=True)

        # All recovery attempts failed
        msg = (
            "Authentication expired. Run 'nlm login' in your terminal to re-authenticate. "
            "MCP users: the server should auto-detect the new credentials; "
            "if not, call the refresh_auth tool."
        )
        if os.environ.get("NOTEBOOKLM_COOKIES"):
            msg += (
                " NOTE: NOTEBOOKLM_COOKIES is set in your environment and overrides "
                "all other auth sources. Update it in your MCP config file and restart."
            )
        raise AuthenticationError(msg)

    # =========================================================================
    # Authentication Management
    # =========================================================================

    def _refresh_auth_tokens(self) -> None:
        """
        Refresh CSRF token and session ID by fetching the NotebookLM homepage.

        This method fetches the NotebookLM page using the stored cookies and
        extracts the CSRF token (SNlM0e) and session ID (FdrFJe) from the HTML.

        Raises:
            ValueError: If cookies are expired (redirected to login) or tokens not found
        """
        # Use httpx.Cookies for proper domain filtering
        cookies = self._get_httpx_cookies()

        # Must use browser-like headers for page fetch
        headers = self._PAGE_FETCH_HEADERS.copy()

        # Use a temporary client for the page fetch. Before the fetch, touch
        # Google's RotateCookies endpoint as a non-fatal freshness recovery
        # step. This helps when the short-lived *PSIDTS cookies are stale while
        # the browser profile can still rotate them.
        with httpx.Client(
            cookies=cookies, headers=headers, follow_redirects=True, timeout=15.0
        ) as client:
            from .cookie_rotation import rotate_google_cookies

            rotate_google_cookies(client)
            response = client.get(f"{self._get_base_url()}/")

            # Check if redirected to login (cookies expired)
            if "accounts.google.com" in str(response.url):
                raise ValueError(
                    "Authentication expired. AI assistants: Run `nlm login` via Bash/terminal tool to re-authenticate automatically. Users: Run `nlm login` in your terminal."
                )

            if response.status_code != 200:
                raise ValueError(f"Failed to fetch NotebookLM page: HTTP {response.status_code}")

            html = response.text

            # Extract CSRF token — try multiple known key names in case Google changes
            # the primary key (SNlM0e). Falls back to 'at=' and 'FdrFJe' patterns.
            from .auth import extract_csrf_from_page_source

            csrf_token = extract_csrf_from_page_source(html)
            if not csrf_token:
                # Save HTML for debugging
                from notebooklm_tools.utils.config import get_storage_dir

                debug_dir = get_storage_dir()
                debug_path = debug_dir / "debug_page.html"
                debug_path.write_text(html, encoding="utf-8")
                import contextlib as _ctxlib

                with _ctxlib.suppress(OSError):
                    debug_path.chmod(0o600)
                raise ValueError(
                    f"Could not extract CSRF token from page. "
                    f"Page saved to {debug_path} for debugging. "
                    f"The page structure may have changed."
                )

            # Extract session ID (FdrFJe) - optional but helps
            sid_match = re.search(r'"FdrFJe":"([^"]+)"', html)

            # Extract build label (cfb2h) - keeps bl param current
            bl_match = re.search(r'"cfb2h":"([^"]+)"', html)

            with self._state_lock:
                from .cookie_rotation import snapshot_cookie_input

                self.cookies = snapshot_cookie_input(self.cookies, client.cookies)
                self.csrf_token = csrf_token
                if sid_match:
                    self._session_id = sid_match.group(1)
                if bl_match:
                    self._bl = bl_match.group(1)

            # Cache the extracted tokens to avoid re-fetching the page on next request
            self._update_cached_tokens()

    def _update_cached_tokens(self) -> None:
        """Update the cached auth tokens with newly extracted CSRF token and session ID.

        This avoids re-fetching the NotebookLM page on every client initialization,
        significantly improving performance for subsequent API calls.
        """
        try:
            import time

            from .auth import AuthTokens, load_cached_tokens, save_tokens_to_cache

            # Load existing cache or create new
            cached = load_cached_tokens(profile_name=self._profile_name)
            if cached:
                # Update existing cache with new tokens
                cached.cookies = self.cookies
                cached.csrf_token = self.csrf_token
                cached.session_id = self._session_id
                if self._bl:
                    cached.build_label = self._bl
            else:
                # Create new cache entry
                cached = AuthTokens(
                    cookies=self.cookies,
                    csrf_token=self.csrf_token,
                    session_id=self._session_id,
                    build_label=self._bl,
                    extracted_at=time.time(),
                )

            save_tokens_to_cache(cached, silent=True, profile_name=self._profile_name)
        except Exception as e:
            # Non-critical: caching is an optimization, but log at debug level
            logger.debug(f"Failed to update auth token cache: {e}")

    def _try_reload_or_headless_auth(self) -> bool:
        """Try to recover authentication by reloading from disk or running headless auth.

        Returns True if new valid tokens were obtained, False otherwise.
        """
        from .auth import load_cached_tokens

        # Layer 2: Reload cookies from the same profile on disk. The configured
        # default may also fall back to legacy auth.json for compatibility.
        cached = load_cached_tokens(profile_name=self._profile_name)
        if cached and cached.cookies:
            # Always reload from disk when auth fails - current tokens are known-bad
            # The cached tokens may be fresher (user ran nlm login)
            # or the same, but worth retrying with a fresh CSRF token extraction
            with self._state_lock:
                self.cookies = cached.cookies
                self.csrf_token = ""  # Force re-extraction of CSRF token
                self._session_id = ""  # Force re-extraction of session ID
            return True

        # Try headless auth for the same profile that owns this client.
        try:
            from notebooklm_tools.utils.auth_browser import run_headless_auth
            from notebooklm_tools.utils.config import get_config

            profile_name = self._profile_name or get_config().auth.default_profile
            tokens = run_headless_auth(profile_name=profile_name)
            if tokens:
                with self._state_lock:
                    self.cookies = tokens.cookies
                    self.csrf_token = tokens.csrf_token
                    self._session_id = tokens.session_id
                return True
        except Exception as e:
            logger.debug(f"Headless auth failed: {e}")

        return False
