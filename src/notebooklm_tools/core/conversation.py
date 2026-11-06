#!/usr/bin/env python3
"""Conversation and query mixin for NotebookLM client.

This module provides the ConversationMixin class which handles all query
and conversation-related operations.
"""

import json
import logging
import os
import time
import urllib.parse
from typing import Any, Protocol, cast

import httpx as _httpx

from .base import BaseClient
from .data_types import ConversationTurn
from .errors import NotebookLMError

logger = logging.getLogger("notebooklm_mcp.api")

DEFAULT_QUERY_TIMEOUT = 120.0

GOOGLE_ERROR_CODES = {
    1: "CANCELLED",
    2: "UNKNOWN",
    3: "INVALID_ARGUMENT",
    4: "DEADLINE_EXCEEDED",
    5: "NOT_FOUND",
    7: "PERMISSION_DENIED",
    8: "RESOURCE_EXHAUSTED",
    13: "INTERNAL",
    14: "UNAVAILABLE",
    16: "UNAUTHENTICATED",
}


class QueryRejectedError(NotebookLMError):
    """Raised when Google returns an error response instead of an answer."""

    def __init__(self, error_code: int, error_type: str = "", raw_detail: str = "") -> None:
        code_name = GOOGLE_ERROR_CODES.get(error_code, "UNKNOWN")
        msg = f"Google rejected the query (error code {error_code}: {code_name})"
        if error_type:
            msg += f" [{error_type}]"
        super().__init__(msg)
        self.error_code = error_code
        self.code_name = code_name
        self.error_type = error_type
        self.raw_detail = raw_detail


class _NotebookLookupProtocol(Protocol):
    def get_notebook(self, notebook_id: str, timeout: float | None = None) -> Any: ...


class ConversationMixin(BaseClient):
    """Mixin providing query and conversation operations.

    Methods:
        - query: Query the notebook with questions
        - clear_conversation: Clear conversation cache
        - get_conversation_history: Get conversation history
    """

    # =========================================================================
    # Conversation Cache Management
    # =========================================================================

    def _build_conversation_history(
        self, conversation_id: str
    ) -> list[list[str | None | int]] | None:
        """Build the conversation history array for follow-up queries.

        Chrome expects history in format: [[answer, null, 2], [query, null, 1], ...]
        where type 1 = user message, type 2 = AI response.

        The history includes ALL previous turns, not just the most recent one.
        Turns are added in chronological order (oldest first).

        Args:
            conversation_id: The conversation ID to get history for

        Returns:
            List in Chrome's expected format, or None if no history exists
        """
        with self._state_lock:
            if conversation_id in self._conversation_cache:
                # Mark as recently used for LRU eviction.
                self._conversation_cache.move_to_end(conversation_id)
                turns = list(self._conversation_cache[conversation_id])
            else:
                turns = []
        if not turns:
            return None

        history = []
        # Add turns in chronological order (oldest first)
        # Each turn adds: [answer, null, 2] then [query, null, 1]
        for turn in turns:
            history.append([turn.answer, None, 2])
            history.append([turn.query, None, 1])

        return history if history else None

    def _cache_conversation_turn(self, conversation_id: str, query: str, answer: str) -> None:
        """Cache a conversation turn for future follow-up queries.

        The cache is bounded (Issue #213) so long-lived MCP server processes don't
        grow without bound:
        - Each conversation keeps only the last `_max_turns_per_conversation` turns
          (FIFO; oldest dropped first). Turn numbers are preserved from the
          original sequence, so the surviving turns keep their original indices.
        - The whole dict is LRU-bounded to `_max_conversations` conversations. On
          overflow, the least-recently-used conversation is evicted.
        - Each turn's answer is truncated to `_max_chars_per_turn` characters as a
          safety net against pathological payloads.

        Set any knob to 0 in the constructor's env vars to disable that specific
        cap (useful for tests).
        """
        with self._state_lock:
            # Per-turn answer truncation (safety net; queries are user input and
            # not truncated).
            if self._max_chars_per_turn > 0 and len(answer) > self._max_chars_per_turn:
                answer = answer[: self._max_chars_per_turn]

            if conversation_id not in self._conversation_cache:
                # New conversation — evict LRU first if at capacity.
                if (
                    self._max_conversations > 0
                    and len(self._conversation_cache) >= self._max_conversations
                ):
                    self._conversation_cache.popitem(last=False)
                self._conversation_cache[conversation_id] = []
            else:
                # Existing conversation — mark as recently used.
                self._conversation_cache.move_to_end(conversation_id)

            turn_number = len(self._conversation_cache[conversation_id]) + 1
            turn = ConversationTurn(query=query, answer=answer, turn_number=turn_number)
            self._conversation_cache[conversation_id].append(turn)

            # Per-conversation turn list trim (FIFO from the front). Renumber
            # survivors so `turn_number` always means "1-indexed position in the
            # current list" (matches the original unbounded-cache semantics from
            # the caller's perspective).
            if (
                self._max_turns_per_conversation > 0
                and len(self._conversation_cache[conversation_id])
                > self._max_turns_per_conversation
            ):
                kept = self._conversation_cache[conversation_id][
                    -self._max_turns_per_conversation :
                ]
                self._conversation_cache[conversation_id] = [
                    ConversationTurn(query=t.query, answer=t.answer, turn_number=i)
                    for i, t in enumerate(kept, start=1)
                ]

    def clear_conversation(self, conversation_id: str) -> bool:
        """Clear the conversation cache for a specific conversation."""
        with self._state_lock:
            if conversation_id in self._conversation_cache:
                del self._conversation_cache[conversation_id]
                return True
            return False

    def get_conversation_history(self, conversation_id: str) -> list[dict[str, str | int]] | None:
        """Get the conversation history for a specific conversation."""
        with self._state_lock:
            if conversation_id in self._conversation_cache:
                self._conversation_cache.move_to_end(conversation_id)
                turns = list(self._conversation_cache[conversation_id])
            else:
                turns = []
        if not turns:
            return None

        return [{"turn": t.turn_number, "query": t.query, "answer": t.answer} for t in turns]

    def get_conversation_cache_stats(self) -> dict[str, int]:
        """Return introspection stats about the bounded conversation cache.

        Useful for debugging, tests, and exposing memory pressure via tooling.

        Note: `conversations` and `total_turns` are captured under the lock; the
        cap fields are immutable post-init, so the small window between release
        and dict construction is harmless.
        """
        with self._state_lock:
            conv_count = len(self._conversation_cache)
            total_turns = sum(len(turns) for turns in self._conversation_cache.values())
        return {
            "conversations": conv_count,
            "total_turns": total_turns,
            "max_turns_per_conversation": self._max_turns_per_conversation,
            "max_conversations": self._max_conversations,
            "max_chars_per_turn": self._max_chars_per_turn,
        }

    def get_conversation_id(self, notebook_id: str, timeout: float | None = None) -> str | None:
        """Fetch the persistent conversation ID for a notebook from the server.

        NotebookLM assigns each notebook a persistent conversation ID that tracks
        chat history across sessions. This ID is what makes chats appear in the
        web UI's chat panel.

        Args:
            notebook_id: The notebook UUID

        Returns:
            The conversation UUID string if one exists, or None for new notebooks.
        """
        try:
            kwargs = {"timeout": timeout} if timeout is not None else {}
            result = self._call_rpc(
                self.RPC_GET_CONVERSATIONS,
                [[], None, notebook_id, 20],
                path=f"/notebook/{notebook_id}",
                **kwargs,
            )
        except Exception:
            # Non-critical: fall back to generating a new UUID
            logger.debug("Failed to fetch conversation ID for notebook %s", notebook_id)
            return None

        # Response format: [[[conv_id]]] — triple-nested array
        if result and isinstance(result, list):
            try:
                # Navigate: result[0] -> [conv_id] or [[conv_id]]
                level1 = result[0]
                if isinstance(level1, list) and len(level1) > 0:
                    level2 = level1[0]
                    if isinstance(level2, str):
                        return level2
                    elif isinstance(level2, list) and len(level2) > 0:  # noqa: SIM102
                        if isinstance(level2[0], str):
                            return level2[0]
            except (IndexError, TypeError):
                pass
        return None

    def get_conversation_turns(
        self, notebook_id: str, conversation_id: str, limit: int = 20
    ) -> list[dict[str, str | int]] | None:
        """Fetch the full Q&A turn history for a conversation from the server.

        Unlike get_conversation_history() (which only returns turns cached in
        this process's memory), this calls NotebookLM's server-side
        conversation-turns RPC, so past chat turns are visible even from a
        fresh CLI invocation or MCP session that hasn't run any queries yet
        (e.g. for `nlm chats get` / `chat_get`).

        Args:
            notebook_id: The notebook UUID (used for the source-path request
                param only; NotebookLM keys the lookup by conversation_id)
            conversation_id: The conversation UUID (from get_conversation_id)
            limit: Max number of turns to fetch from the server (default: 20)

        Returns:
            List of {"turn": int, "query": str, "answer": str} dicts in
            chronological order (oldest first), or None if the server
            returned no turns (new/empty conversation) or the call failed.
        """
        try:
            result = self._call_rpc(
                self.RPC_GET_CONVERSATION_TURNS,
                [
                    [
                        2,
                        None,
                        [1],
                        [1, None, None, None, None, None, None, None, None, None, [1, 3]],
                    ],
                    None,
                    None,
                    conversation_id,
                    limit,
                ],
                path=f"/notebook/{notebook_id}",
            )
        except Exception:
            logger.debug(
                "Failed to fetch server conversation turns for conversation %s",
                conversation_id,
            )
            return None

        # Response format: [[turn, turn, ...], continuation_token]. Turns
        # alternate newest-first: [answer_turn, query_turn, answer_turn, ...]
        #   answer_turn = [turn_id, [sec, nsec], 2, None, [[answer_text, ...], ...]]
        #   query_turn  = [turn_id, [sec, nsec], 1, query_text]
        # The answer text is nested one level inside content[0] (itself
        # [answer_text, None, [conv_id, conv_id, num]]), not content[0] directly.
        if not result or not isinstance(result, list):
            return None
        raw_turns = result[0] if result else None
        if not isinstance(raw_turns, list) or not raw_turns:
            return None

        pairs: list[tuple[str, str]] = []  # (query, answer), newest first
        pending_answer: str | None = None
        for entry in raw_turns:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            turn_type = entry[2]
            if turn_type == 2 and len(entry) > 4 and isinstance(entry[4], list) and entry[4]:
                answer_wrapper = entry[4][0]
                if (
                    isinstance(answer_wrapper, list)
                    and answer_wrapper
                    and isinstance(answer_wrapper[0], str)
                ):
                    pending_answer = answer_wrapper[0]
                else:
                    pending_answer = ""
            elif turn_type == 1 and len(entry) > 3 and isinstance(entry[3], str):
                if pending_answer is not None:
                    pairs.append((entry[3], pending_answer))
                    pending_answer = None

        if not pairs:
            return None

        # Server returns newest-first; reverse to chronological order.
        pairs.reverse()
        return [{"turn": i, "query": q, "answer": a} for i, (q, a) in enumerate(pairs, start=1)]

    def delete_chat_history(self, notebook_id: str, conversation_id: str) -> bool:
        """Delete the chat history for a notebook.

        Args:
            notebook_id: The notebook UUID
            conversation_id: The conversation UUID to delete

        Returns:
            True if the deletion was acknowledged by the server.
        """
        # Captured from the web UI: consumer header, conversation ID, null, 1.
        # The notebook ID is carried by source-path, not this body.
        result = self._call_rpc(
            self.RPC_DELETE_CHAT_HISTORY,
            [
                [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]],
                conversation_id,
                None,
                1,
            ],
            path=f"/notebook/{notebook_id}",
            retry_server_errors=False,
        )
        # Also clear local cache if present
        with self._state_lock:
            self._conversation_cache.pop(conversation_id, None)
        return result is not None

    # =========================================================================
    # Query Operations
    # =========================================================================

    def query(
        self,
        notebook_id: str,
        query_text: str,
        source_ids: list[str] | None = None,
        conversation_id: str | None = None,
        timeout: float | None = DEFAULT_QUERY_TIMEOUT,
        new_conversation: bool = False,
    ) -> dict[str, Any] | None:
        """Query the notebook with a question.

        Supports both new conversations and follow-up queries. For follow-ups,
        the conversation history is automatically included from the cache.

        Args:
            notebook_id: The notebook UUID
            query_text: The question to ask
            source_ids: Optional list of source IDs to query (default: all sources)
            conversation_id: Optional conversation ID for follow-up questions.
                           If None, reuses the notebook's persistent server
                           conversation when one exists.
                           If provided and exists in cache, includes conversation history.
            timeout: Wall-clock query budget in seconds (default: 120.0)
            new_conversation: If True and conversation_id is omitted, always
                              starts a fresh conversation with a generated UUID.

        Returns:
            Dict with:
            - answer: The AI's response text
            - conversation_id: ID to use for follow-up questions
            - sources_used: List of source IDs cited in the answer
            - citations: Dict mapping citation number to source ID (1-indexed)
            - references: List of dicts with source_id, citation_number, and
              cited_text (the actual passage text from the source)
            - turn_number: Which turn this is in the conversation (1 = first)
            - is_follow_up: Whether this was a follow-up query
        """
        import uuid

        deadline = time.monotonic() + timeout if timeout is not None else None

        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _httpx.ReadTimeout("The query deadline expired before the next request")
            return remaining

        # If no source_ids provided, get them from the notebook
        if source_ids is None:
            if getattr(self, "_is_enterprise", lambda: False)():
                all_nbs = cast(_NotebookLookupProtocol, self).list_notebooks()
                target_nb = next((nb for nb in all_nbs if nb.id == notebook_id), None)
                source_ids = (
                    [s["id"] for s in target_nb.sources] if target_nb and target_nb.sources else []
                )
            else:
                notebook_client = cast(_NotebookLookupProtocol, self)
                notebook_data = notebook_client.get_notebook(
                    notebook_id, timeout=remaining_timeout()
                )
                source_ids = self._extract_source_ids_from_notebook(notebook_data)

        # Determine if this is a new conversation or follow-up
        is_new_conversation = conversation_id is None
        if is_new_conversation:
            if new_conversation:
                conversation_id = str(uuid.uuid4())
                conversation_history = None
            else:
                # Enterprise's streamed route does not expose the consumer
                # conversation lookup RPC. Start with a local ID there.
                if self._is_enterprise():
                    conversation_id = str(uuid.uuid4())
                    conversation_history = None
                else:
                    # This is what makes consumer CLI/MCP chats appear in the
                    # web UI's chat history.
                    server_conv_id = self.get_conversation_id(
                        notebook_id, timeout=remaining_timeout()
                    )
                    if server_conv_id:
                        conversation_id = server_conv_id
                        conversation_history = self._build_conversation_history(conversation_id)
                    else:
                        conversation_id = str(uuid.uuid4())
                        conversation_history = None
        else:
            # Check if we have cached history for this conversation
            assert conversation_id is not None
            conversation_history = self._build_conversation_history(conversation_id)

        assert conversation_id is not None

        request_timeout = remaining_timeout()

        if self._cdp_rpc_transport_enabled():
            self._prepare_cdp_transport(request_timeout)

        # Build source IDs structure: [[[sid]]] for each source (3 brackets, not 4!)
        sources_array = [[[sid]] for sid in source_ids] if source_ids else []

        params: list[Any]
        if getattr(self, "_is_enterprise", lambda: False)():
            # Enterprise query params structure:
            # [[[[sid]]], query, {"70000": "projects/{project_id}/locations/{location}/notebooks/{notebook_id}"}]
            from notebooklm_tools.utils.config import (
                get_enterprise_location,
                get_enterprise_project_id,
            )

            project_id = getattr(self, "_enterprise_project_id", "") or get_enterprise_project_id()
            loc = getattr(self, "_location", "") or get_enterprise_location()
            project_prefix = f"projects/{project_id}/" if project_id else ""
            resource_name = f"{project_prefix}locations/{loc}/notebooks/{notebook_id}"
            params = [
                sources_array,
                query_text,
                {"70000": resource_name},
            ]
        else:
            # Consumer GenerateFreeFormStreamed 9-slot request structure
            # (boq_labs-tailwind-frontend_20261105.11_p0):
            #   [0] sources_array: [[[sid]], ...]
            #   [1] query_text
            #   [2] conversation_history: None for new, [[answer, null, 2], [query, null, 1], ...] for follow-ups
            #   [3] client capability descriptor (same 4-slot header used by khqZz and e3bVqc/delete_chat_history)
            #   [4] conversation_id
            #   [5] drafted_context (None)
            #   [6] tool_executions (None)
            #   [7] notebook_id
            #   [8] query_mode (1)
            params = [
                sources_array,
                query_text,
                conversation_history,  # None for new, history array for follow-ups
                [
                    2,
                    None,
                    [1],
                    [1, None, None, None, None, None, None, None, None, None, [1, 3]],
                ],
                conversation_id,
                None,
                None,
                notebook_id,
                1,
            ]

        # Use compact JSON format matching Chrome (no spaces)
        params_json = json.dumps(params, separators=(",", ":"), ensure_ascii=False)

        f_req = [None, params_json]
        f_req_json = json.dumps(f_req, separators=(",", ":"), ensure_ascii=False)

        if (
            not self.csrf_token
            or (getattr(self, "_is_enterprise", lambda: False)() and not self._session_id)
        ) and not self._cdp_rpc_transport_enabled():
            try:
                self._refresh_auth_tokens()
            except Exception:
                if not self.csrf_token:
                    raise

        # URL encode with safe='' to encode all characters including /
        body_parts = [f"f.req={urllib.parse.quote(f_req_json, safe='')}"]
        if self.csrf_token:
            body_parts.append(f"at={urllib.parse.quote(self.csrf_token, safe='')}")
        # Add trailing & to match NotebookLM's format
        body = "&".join(body_parts) + "&"

        with self._state_lock:
            self._reqid_counter += 100000
            reqid = self._reqid_counter
        fallback_bl = (
            getattr(self, "_BL_FALLBACK_ENTERPRISE", self._BL_FALLBACK)
            if getattr(self, "_is_enterprise", lambda: False)()
            else self._BL_FALLBACK
        )
        url_params = {
            "bl": os.environ.get("NOTEBOOKLM_BL") or getattr(self, "_bl", "") or fallback_bl,
            "hl": os.environ.get("NOTEBOOKLM_HL", "en"),
            "_reqid": str(reqid),
            "rt": "c",
        }
        if self._session_id:
            url_params["f.sid"] = self._session_id

        query_string = urllib.parse.urlencode(url_params)
        endpoint = getattr(self, "_get_query_endpoint", lambda: self.QUERY_ENDPOINT)()
        url = f"{self._get_base_url()}{endpoint}?{query_string}"

        cookies = self._get_httpx_cookies()
        # The streamed query endpoint is stricter than batchexecute and rejects
        # form-encoded payloads without an explicit Content-Type header.
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}
        if self._cdp_rpc_transport_enabled():
            response_text = self._post_form_via_cdp(url, body, request_timeout)
        else:
            with _httpx.Client(timeout=request_timeout, cookies=cookies, headers=headers) as client:
                response = client.post(url, content=body)
                response.raise_for_status()
                response_text = response.text

        logger.debug("Raw query response (first 2000 chars): %s", response_text[:2000])

        # Parse streaming response
        answer_text, citation_data, server_conv_id = self._parse_query_response(response_text)

        # If the server assigned a conversation ID in the response, use it.
        # This is the key mechanism for chat history persistence — the server
        # returns its own conversation ID which tracks the chat across sessions.
        if server_conv_id and server_conv_id != conversation_id:
            with self._state_lock:
                # Migrate local cache to the server-assigned ID. Use
                # move_to_end unconditionally so the migrated key is at MRU
                # even if server_conv_id was already in the cache (in which
                # case the assignment doesn't reorder it on its own).
                if conversation_id in self._conversation_cache:
                    self._conversation_cache[server_conv_id] = self._conversation_cache.pop(
                        conversation_id
                    )
                self._conversation_cache.move_to_end(server_conv_id)
            conversation_id = server_conv_id

        # Cache this turn for future follow-ups (only if we got an answer)
        if answer_text:
            self._cache_conversation_turn(conversation_id, query_text, answer_text)

        # Calculate turn number
        with self._state_lock:
            turns = self._conversation_cache.get(conversation_id, [])
            turn_number = len(turns)

        return {
            "answer": answer_text,
            "conversation_id": conversation_id,
            "sources_used": citation_data.get("sources_used", []),
            "citations": citation_data.get("citations", {}),
            "references": citation_data.get("references", []),
            "turn_number": turn_number,
            "is_follow_up": not is_new_conversation,
        }

    def _extract_source_ids_from_notebook(self, notebook_data: Any) -> list[str]:
        """Extract source IDs from notebook data."""
        source_ids: list[str] = []
        if not notebook_data or not isinstance(notebook_data, list):
            return source_ids

        try:
            # Notebook structure: [[notebook_title, sources_array, notebook_id, ...]]
            # The outer array contains one element with all notebook info
            # Sources are at position [0][1]
            if len(notebook_data) > 0 and isinstance(notebook_data[0], list):
                notebook_info = notebook_data[0]
                if len(notebook_info) > 1 and isinstance(notebook_info[1], list):
                    sources = notebook_info[1]
                    for source in sources:
                        # Each source: [[source_id], title, metadata, [null, 2]]
                        if isinstance(source, list) and len(source) > 0:
                            source_id_wrapper = source[0]
                            if isinstance(source_id_wrapper, list) and len(source_id_wrapper) > 0:
                                source_id = source_id_wrapper[0]
                                if isinstance(source_id, str):
                                    source_ids.append(source_id)
        except (IndexError, TypeError):
            pass

        return source_ids

    # =========================================================================
    # Response Parsing
    # =========================================================================

    def _parse_query_response(self, response_text: str) -> tuple[str, dict[str, Any], str | None]:
        """Parse the streaming response from the query endpoint.

        The query endpoint returns a streaming response with multiple chunks.
        Each chunk has a type indicator: 1 = actual answer, 2 = thinking step.

        Strategy: Find the LONGEST chunk that is marked as type 1 (actual answer).
        If no type 1 chunks found, fall back to longest overall.
        If no answer at all but Google returned an error, raise QueryRejectedError.

        Returns:
            Tuple of (answer_text, citation_data, server_conversation_id)
            where server_conversation_id is the ID assigned by the NotebookLM
            backend (used for persistent chat history), or None if not found.
        """
        # Remove anti-XSSI prefix
        start_offset = 4 if response_text.startswith(")]}'") else 0

        def _iter_lines():
            """Yield response lines without materializing the full body."""
            line_start = start_offset
            response_length = len(response_text)
            while line_start < response_length:
                line_end = response_text.find("\n", line_start)
                if line_end == -1:
                    yield response_text[line_start:]
                    return
                yield response_text[line_start:line_end]
                line_start = line_end + 1

        longest_answer = ""
        longest_thinking = ""
        answer_citation_data: dict[str, Any] = {}
        detected_errors: list[dict[str, Any]] = []
        server_conv_id: str | None = None

        def _process_chunk(json_line: str) -> None:
            nonlocal longest_answer, longest_thinking, answer_citation_data, server_conv_id
            error = self._extract_error_from_chunk(json_line)
            if error:
                detected_errors.append(error)
                return
            text, is_answer, cdata, chunk_conv_id = self._extract_answer_from_chunk(json_line)
            if text:
                if is_answer and len(text) > len(longest_answer):
                    longest_answer = text
                    if cdata:
                        answer_citation_data = cdata
                    if chunk_conv_id:
                        server_conv_id = chunk_conv_id
                elif not is_answer and len(text) > len(longest_thinking):
                    longest_thinking = text

        # Parse chunks - prioritize type 1 (answers) over type 2 (thinking)
        lines = iter(_iter_lines())
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue

            # Try to parse as byte count (indicates next line is JSON)
            try:
                int(line)
                json_line = next(lines, None)
                if json_line is not None:
                    _process_chunk(json_line)
            except ValueError:
                _process_chunk(line)

        result = longest_answer if longest_answer else longest_thinking

        if not result and detected_errors:
            err = detected_errors[0]
            raise QueryRejectedError(
                error_code=err["code"],
                error_type=err.get("type", ""),
                raw_detail=err.get("raw", ""),
            )

        return result, answer_citation_data, server_conv_id

    def _extract_error_from_chunk(self, json_str: str) -> dict[str, Any] | None:
        """Check if a JSON chunk contains a Google API error.

        Error responses have item[2] as null/None and error info in item[5]:
          [["wrb.fr", null, null, null, null, [3]]]
          [["wrb.fr", null, null, null, null, [8, null, [["type.googleapis.com/...Error", [...]]]]]]

        Returns:
            Dict with 'code', 'type', 'raw' keys if error found, else None
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, list) or len(data) == 0:
            return None

        for item in data:
            if not isinstance(item, list) or len(item) < 6:
                continue
            if item[0] != "wrb.fr":
                continue
            if item[2] is not None:
                continue

            error_info = item[5]
            if not isinstance(error_info, list) or len(error_info) == 0:
                continue

            error_code = error_info[0]
            if not isinstance(error_code, int):
                continue

            error_type = ""
            if len(error_info) > 2 and isinstance(error_info[2], list):
                for detail in error_info[2]:
                    if isinstance(detail, list) and len(detail) > 0 and isinstance(detail[0], str):
                        error_type = detail[0]
                        break

            return {
                "code": error_code,
                "type": error_type,
                "raw": json_str[:500],
            }

        return None

    def _extract_answer_from_chunk(
        self, json_str: str
    ) -> tuple[str | None, bool, dict[str, Any], str | None]:
        """Extract answer text, citation data, and server-assigned conversation ID from a single JSON chunk.

        The chunk structure is:
        [["wrb.fr", null, "<nested_json>", ...]]

        The nested_json contains:
        [["answer_text", null, [conv_id, hash, timestamp], null, [fmt_segments, null, null, source_passages, type_code]]]

        type_code: 1 = actual answer, 2 = thinking step
        source_passages (at first_elem[4][3]): list of passage entries, each containing
        the parent source ID at passage[1][5][0][0][0].

        Args:
            json_str: A single JSON chunk from the response

        Returns:
            Tuple of (text, is_answer, citation_data, server_conv_id) where:
            - is_answer is True for actual answers (type 1)
            - citation_data is {"sources_used": [...], "citations": {num: source_id}}
              or empty dict if no citation data found
            - server_conv_id is the conversation ID assigned by the server, or None
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None, False, {}, None

        if not isinstance(data, list) or len(data) == 0:
            return None, False, {}, None

        for item in data:
            if not isinstance(item, list) or len(item) < 3:
                continue
            if item[0] != "wrb.fr":
                continue

            inner_json_str = item[2]
            if not isinstance(inner_json_str, str):
                continue

            try:
                inner_data = json.loads(inner_json_str)
            except json.JSONDecodeError:
                continue

            # Type indicator is at inner_data[0][4][-1]: 1 = answer, 2 = thinking
            if isinstance(inner_data, list) and len(inner_data) > 0:
                first_elem = inner_data[0]
                if isinstance(first_elem, list) and len(first_elem) > 0:
                    answer_text = first_elem[0]
                    if isinstance(answer_text, str):
                        is_answer = False
                        citation_data: dict[str, Any] = {}
                        server_conv_id: str | None = None

                        # Extract server-assigned conversation ID from conv_data
                        # Structure: first_elem[2] = [conv_id, hash, timestamp]
                        if len(first_elem) > 2 and isinstance(first_elem[2], list):
                            conv_data = first_elem[2]
                            if len(conv_data) > 0 and isinstance(conv_data[0], str):
                                server_conv_id = conv_data[0]

                        if len(first_elem) > 4 and isinstance(first_elem[4], list):
                            type_info = first_elem[4]
                            if len(type_info) > 0 and isinstance(type_info[-1], int):
                                is_answer = type_info[-1] == 1
                            if is_answer:
                                citation_data = self._extract_citation_data(type_info)
                        return answer_text, is_answer, citation_data, server_conv_id
                elif isinstance(first_elem, str):
                    return first_elem, False, {}, None

        return None, False, {}, None

    @staticmethod
    def _extract_cited_text(detail: list[Any]) -> str | None:
        """Extract cited text from a passage detail structure.

        The text passages are at detail[4], which contains elements in two variants:
          - Wrapped segments: [[start, end, nested], metadata] — first element is a list
          - Direct segments: [start, end, nested] — first element is an integer
        Each segment has nested_passages containing text as [start, end, text] triplets.

        Args:
            detail: The inner detail array (passage[1]).

        Returns:
            Concatenated cited text string, or None if no text found.
        """
        if len(detail) <= 4 or not isinstance(detail[4], list):
            return None

        texts: list[str] = []
        for element in detail[4]:
            if not isinstance(element, list) or not element:
                continue

            # Detect: is this a direct segment [int, int, nested] or a wrapper [[seg], ...]?
            if isinstance(element[0], (int, float)):  # noqa: SIM108
                # Direct segment
                segments_to_process = [element]
            else:
                # Wrapper containing segments (and possibly metadata like [null, 1])
                segments_to_process = element

            for segment in segments_to_process:
                if not isinstance(segment, list) or len(segment) < 3:
                    continue
                if not isinstance(segment[0], (int, float)):
                    continue
                nested = segment[2]
                if not isinstance(nested, list):
                    # Table segment: insert placeholder, data goes in cited_table
                    if (
                        len(segment) > 4
                        and isinstance(segment[4], list)
                        and len(segment[4]) >= 3
                        and isinstance(segment[4][2], list)
                    ):
                        texts.append("<cited_table>")
                    continue
                for nested_group in nested:
                    if not isinstance(nested_group, list):
                        continue
                    for inner in nested_group:
                        if not isinstance(inner, list) or len(inner) < 3:
                            continue
                        text_val = inner[2]
                        if isinstance(text_val, str) and text_val.strip():
                            texts.append(text_val.strip())
                        elif isinstance(text_val, list):
                            for item in text_val:
                                if isinstance(item, str) and item.strip():
                                    texts.append(item.strip())

        return " ".join(texts) if texts else None

    @staticmethod
    def _extract_text_from_table_rows(rows: list[Any]) -> list[list[str]]:
        """Parse table rows into a structured list of rows, each a list of cell strings.

        Table segments have their data at segment[4] = [dim1, dim2, rows_array].
        Each row:  [start, end, [cells...]]
        Each cell: [start, end, [[sub_start, sub_end, [content_items...]]]]
                   or [start, start] (empty cell)
        Each content_item: [[text_start, text_end, [text, ...]], optional_metadata]

        Returns:
            List of rows, where each row is a list of cell text strings.
        """
        parsed_rows: list[list[str]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 3:
                continue
            cells = row[2]
            if not isinstance(cells, list):
                continue
            row_cells: list[str] = []
            for cell in cells:
                cell_text = ""
                if isinstance(cell, list) and len(cell) >= 3:
                    cell_content = cell[2]
                    if isinstance(cell_content, list):
                        parts: list[str] = []
                        for sub_elem in cell_content:
                            if not isinstance(sub_elem, list) or len(sub_elem) < 3:
                                continue
                            content_items = sub_elem[2]
                            if not isinstance(content_items, list):
                                continue
                            for item in content_items:
                                if not isinstance(item, list) or not item:
                                    continue
                                first = item[0]
                                if not isinstance(first, list) or len(first) < 3:
                                    continue
                                text_val = first[2]
                                if isinstance(text_val, list):
                                    for t in text_val:
                                        if isinstance(t, str) and t.strip():
                                            parts.append(t.strip())
                                elif isinstance(text_val, str) and text_val.strip():
                                    parts.append(text_val.strip())
                        cell_text = " ".join(parts)
                row_cells.append(cell_text)
            parsed_rows.append(row_cells)
        return parsed_rows

    @staticmethod
    def _extract_table_from_detail(detail: list[Any]) -> dict[str, Any] | None:
        """Extract structured table data from a passage detail.

        Scans detail[4] for table/grid segments (where segment[2] is null and
        segment[4] holds [dim1, dim2, rows_array]).

        Returns:
            Dict with 'num_columns' and 'rows' (list of lists of cell strings),
            or None if no table found.
        """
        if len(detail) <= 4 or not isinstance(detail[4], list):
            return None

        for element in detail[4]:
            if not isinstance(element, list) or not element:
                continue

            segments = [element] if isinstance(element[0], (int, float)) else element

            for segment in segments:
                if not isinstance(segment, list) or len(segment) < 3:
                    continue
                if not isinstance(segment[0], (int, float)):
                    continue
                # Table segments have segment[2] as null, data in segment[4]
                if isinstance(segment[2], list):
                    continue
                if len(segment) <= 4 or not isinstance(segment[4], list):
                    continue
                table_info = segment[4]
                if len(table_info) < 3 or not isinstance(table_info[2], list):
                    continue

                parsed_rows = ConversationMixin._extract_text_from_table_rows(table_info[2])
                if parsed_rows:
                    return {
                        "num_columns": len(parsed_rows[0]),
                        "rows": parsed_rows,
                    }

        return None

    @staticmethod
    def _extract_citation_data(type_info: list[Any]) -> dict[str, Any]:
        """Extract source IDs and cited text from the citation passages in a type-1 answer chunk.

        The source passages are at type_info[3] (i.e. first_elem[4][3]).
        Each passage entry: [["passage_id"], [null, null, confidence, ..., text_passages, [[["SOURCE_ID"], ...]], ...]]
        The parent source ID is at passage[1][5][0][0][0].
        The cited text passages are at passage[1][4].
        Citations in the answer text are 1-indexed into this array.

        Returns:
            Dict with 'sources_used' (unique source IDs),
            'citations' (citation_number -> source_id mapping),
            and 'references' (list of {source_id, citation_number, cited_text}),
            or empty dict.
        """
        try:
            if len(type_info) < 4 or not isinstance(type_info[3], list):
                return {}

            passages = type_info[3]
            if not passages:
                return {}

            citations: dict[int, str] = {}
            seen_sources: dict[str, None] = {}  # ordered set via dict
            references: list[dict[str, Any]] = []

            for i, passage in enumerate(passages):
                if not isinstance(passage, list) or len(passage) < 2:
                    continue
                detail = passage[1]
                if not isinstance(detail, list) or len(detail) < 6:
                    continue
                source_ref = detail[5]
                if not isinstance(source_ref, list) or len(source_ref) == 0:
                    continue
                first_ref = source_ref[0]
                if not isinstance(first_ref, list) or len(first_ref) == 0:
                    continue
                source_id_wrapper = first_ref[0]
                if not isinstance(source_id_wrapper, list) or len(source_id_wrapper) == 0:
                    continue
                source_id = source_id_wrapper[0]
                if isinstance(source_id, str):
                    citation_number = i + 1
                    citations[citation_number] = source_id
                    seen_sources[source_id] = None

                    # Extract cited text from passage detail
                    cited_text = ConversationMixin._extract_cited_text(detail)

                    ref_entry: dict[str, Any] = {
                        "source_id": source_id,
                        "citation_number": citation_number,
                    }
                    if cited_text:
                        ref_entry["cited_text"] = cited_text

                    # Extract structured table data if present
                    cited_table = ConversationMixin._extract_table_from_detail(detail)
                    if cited_table:
                        ref_entry["cited_table"] = cited_table

                    references.append(ref_entry)

            if not citations:
                return {}

            return {
                "sources_used": list(seen_sources.keys()),
                "citations": citations,
                "references": references,
            }
        except (IndexError, TypeError):
            return {}
