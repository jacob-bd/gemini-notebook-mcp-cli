"""Native NotebookLM read-only passage retrieval via ASU5Oe.

This experimental operation uses the EXISTING authenticated NotebookLM session.
It does not use Gemini/Opal credentials or persist retrieved passage contents.
The native response groups passages by source UUID, not a documented score order.
"""

from __future__ import annotations

import re
from typing import Any

from notebooklm_tools.services import notebooks as notebooks_service

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
RPC_SEARCH_RELEVANT_CHUNKS = "ASU5Oe"
MAX_QUERY_CHARS = 1000
MAX_SOURCE_FILTERS = 10
MAX_RESULTS = 20
MAX_SNIPPET_CHARS = 1800
MAX_TOTAL_CHARS = 12000


class SourceSearchError(ValueError):
    """Input or response error with sanitized, non-content-bearing message."""


def validate_search(
    notebook_id: str,
    query: str,
    source_ids: list[str] | None,
    max_results: int,
    snippet_chars: int,
) -> tuple[str, str, list[str]]:
    """Fail closed on invalid or unbounded search arguments."""
    if not isinstance(notebook_id, str) or not UUID_PATTERN.fullmatch(notebook_id):
        raise SourceSearchError("notebook_id must be a UUID")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise SourceSearchError("query must contain 1 to 1000 characters")
    if (
        not isinstance(max_results, int)
        or isinstance(max_results, bool)
        or not 1 <= max_results <= MAX_RESULTS
    ):
        raise SourceSearchError("max_results must be between 1 and 20")
    if (
        not isinstance(snippet_chars, int)
        or isinstance(snippet_chars, bool)
        or not 1 <= snippet_chars <= MAX_SNIPPET_CHARS
    ):
        raise SourceSearchError("snippet_chars must be between 1 and 1800")
    if source_ids is None:
        return notebook_id.lower(), query.strip(), []
    if not isinstance(source_ids, list) or not 1 <= len(source_ids) <= MAX_SOURCE_FILTERS:
        raise SourceSearchError("source_ids must be a list of 1 to 10 UUIDs")
    if any(not isinstance(sid, str) or not UUID_PATTERN.fullmatch(sid) for sid in source_ids):
        raise SourceSearchError("source_ids must contain only valid UUIDs")
    normalized = [sid.lower() for sid in source_ids]
    if len(set(normalized)) != len(normalized):
        raise SourceSearchError("source_ids cannot contain duplicates")
    return notebook_id.lower(), query.strip(), normalized


def extract_passages(
    result: Any,
    *,
    native_sources: dict[str, str],
    source_filter: set[str] | None,
    max_results: int,
    snippet_chars: int,
) -> dict[str, Any]:
    """Decode only verified source/chunk positions, never guess hidden rankings."""
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], list):
        raise SourceSearchError("NotebookLM returned an unrecognized retrieval structure")
    source_groups = result[0]
    total_available = 0
    excluded_sources = 0
    by_source: dict[str, list[tuple[int, str]]] = {}
    for group in source_groups:
        if not (
            isinstance(group, list)
            and len(group) == 2
            and isinstance(group[0], str)
            and isinstance(group[1], list)
        ):
            continue
        sid = group[0].lower()
        if sid not in native_sources or (source_filter is not None and sid not in source_filter):
            excluded_sources += 1
            continue
        passages = by_source.setdefault(sid, [])
        for index, item in enumerate(group[1]):
            if not (isinstance(item, list) and len(item) >= 1):
                continue
            # Observed shape: [[[[text]]], ordinal/offset, [[...]]].
            nested = item[0]
            if not (
                isinstance(nested, list)
                and len(nested) == 1
                and isinstance(nested[0], list)
                and len(nested[0]) == 1
                and isinstance(nested[0][0], list)
                and len(nested[0][0]) == 1
            ):
                continue
            passage = nested[0][0][0]
            if isinstance(passage, str) and passage.strip():
                passages.append((index, passage))
                total_available += 1

    # The upstream response is grouped by source, without documented global
    # ranking scores. Round-robin prevents the first long source from consuming
    # the entire tool response; preserve passage order within each source.
    hits: list[dict[str, Any]] = []
    emitted_chars = 0
    truncated_by_budget = False
    depth = 0
    while len(hits) < max_results and any(len(v) > depth for v in by_source.values()):
        for sid, passages in by_source.items():
            if len(hits) >= max_results:
                break
            if len(passages) <= depth:
                continue
            remaining = MAX_TOTAL_CHARS - emitted_chars
            if remaining <= 0:
                truncated_by_budget = True
                break
            index, passage = passages[depth]
            excerpt = passage[: min(snippet_chars, remaining)]
            emitted_chars += len(excerpt)
            if len(passage) > len(excerpt):
                truncated_by_budget = True
            hits.append(
                {
                    "source_id": sid,
                    "source_title": native_sources[sid],
                    "passage_ordinal_within_source": index,
                    "excerpt": excerpt,
                    "excerpt_truncated": len(passage) > len(excerpt),
                }
            )
        if emitted_chars >= MAX_TOTAL_CHARS:
            truncated_by_budget = True
            break
        depth += 1
    return {
        "returned_passages": len(hits),
        "available_passages": total_available,
        "returned_sources": len({hit["source_id"] for hit in hits}),
        "selection_policy": "round_robin_by_source",
        "excluded_unknown_or_unrequested_sources": excluded_sources,
        "truncated": total_available > len(hits) or truncated_by_budget,
        "results": hits,
    }


def search_native_sources(
    client: Any,
    notebook_id: str,
    query: str,
    source_ids: list[str] | None = None,
    max_results: int = 8,
    snippet_chars: int = 900,
) -> dict[str, Any]:
    """Search indexed passages, returning bounded excerpts and native UUIDs.

    The source filter is checked against the notebook's current native inventory
    before making the retrieval call, preventing cross-notebook ID confusion.
    """
    notebook_id, query, source_ids = validate_search(
        notebook_id, query, source_ids, max_results, snippet_chars
    )
    details = notebooks_service.get_notebook(client, notebook_id)
    native_sources = {
        source["id"].lower(): source.get("title", "")
        for source in details["sources"]
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    unknown_ids = set(source_ids) - native_sources.keys()
    if unknown_ids:
        raise SourceSearchError("source_ids include IDs absent from the selected notebook")
    params: list[Any] = [notebook_id, query, None, [1]]
    if source_ids:
        params.append([[source_ids]])

    # Do not replay failed requests on 429/5xx. No direct Gemini interaction.
    response = client._call_rpc(
        RPC_SEARCH_RELEVANT_CHUNKS,
        params,
        path=f"/notebook/{notebook_id}",
        timeout=30,
        retry_server_errors=False,
    )
    parsed = extract_passages(
        response,
        native_sources=native_sources,
        source_filter=set(source_ids) if source_ids else None,
        max_results=max_results,
        snippet_chars=snippet_chars,
    )
    return {
        "notebook_id": notebook_id,
        "query": "[omitted]",
        "read_only": True,
        "source_filter_applied": bool(source_ids),
        "complete_source_inventory": False,
        "ranking_score_available": False,
        **parsed,
    }
