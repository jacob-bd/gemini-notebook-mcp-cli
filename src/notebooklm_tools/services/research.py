"""Research service — shared business logic for research start, poll, and import."""

import re
import time
from collections import defaultdict

from ..core.client import NotebookLMClient
from ..core.constants import RESULT_TYPE_DEEP_REPORT
from ..core.errors import RPCDriftError, RPCError
from ._compat import TypedDict
from ._research_import_guard import import_once
from .errors import ServiceError, ValidationError

VALID_SOURCES = ("web", "drive")
VALID_MODES = ("fast", "deep")

# A research task that was just started can be briefly invisible to the poll RPC
# (issue #346). While blocking on a known task_id, an empty poll is retried for up
# to this many seconds before we conclude the task really does not exist.
NO_RESEARCH_GRACE_SECONDS = 90
# Delay between those retries (capped by poll_interval so callers can ask for faster).
NO_RESEARCH_RETRY_INTERVAL = 5

_CITATION_MARKER_RE = re.compile(r"\[([0-9][0-9\s,;\-\u2013\u2014]*)\]")
_BIBLIOGRAPHY_LINE_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$", re.MULTILINE)
_URL_RE = re.compile(r"https?://[^\s<>\])]+")
_TRAILING_URL_CHARS = ".,;:!?)]}"


class ResearchStartResult(TypedDict):
    """Result of starting a research task."""

    task_id: str
    notebook_id: str
    query: str
    source: str
    mode: str
    message: str


class _ResearchStatusOptional(TypedDict, total=False):
    """Additional status fields available when automatic import is requested."""

    imported: bool | None
    import_state: str
    import_error: str
    next_action: str | None


class ResearchStatusResult(_ResearchStatusOptional):
    """Result of polling research status."""

    status: str
    notebook_id: str
    task_id: str | None
    sources_found: int
    sources: list[object]
    report: str
    message: str | None


class ResearchImportResult(TypedDict):
    """Result of importing research sources."""

    notebook_id: str
    imported_count: int
    imported_sources: list[dict[str, object]]
    message: str


def _normalize_url(value: str) -> str:
    """Normalize URLs enough for matching report bibliography links to sources."""
    url = value.strip().strip("<>")
    while url and url[-1] in _TRAILING_URL_CHARS:
        url = url[:-1]
    return url.rstrip("/")


def _extract_urls(text: str) -> list[str]:
    """Extract normalized HTTP(S) URLs while preserving encounter order."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(text):
        url = _normalize_url(match.group(0))
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    return urls


def _expand_citation_numbers(raw: str) -> set[int]:
    """Expand citation expressions such as "1, 3-5" into integer IDs."""
    numbers: set[int] = set()
    for part in re.split(r"\s*[,;]\s*", raw):
        part = part.strip()
        if not part:
            continue

        range_match = re.fullmatch(r"(\d+)\s*[-\u2013\u2014]\s*(\d+)", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start <= end and end - start <= 100:
                numbers.update(range(start, end + 1))
            continue

        if part.isdigit():
            numbers.add(int(part))
    return numbers


def _parse_citation_numbers(report: str) -> set[int]:
    """Return bibliography numbers referenced by inline citation markers."""
    numbers: set[int] = set()
    for match in _CITATION_MARKER_RE.finditer(report):
        numbers.update(_expand_citation_numbers(match.group(1)))
    return numbers


def _parse_bibliography_urls(report: str) -> dict[int, str]:
    """Parse trailing numbered bibliography lines into citation-number URLs."""
    bibliography: dict[int, str] = {}
    for match in _BIBLIOGRAPHY_LINE_RE.finditer(report):
        urls = _extract_urls(match.group(2))
        if urls:
            bibliography[int(match.group(1))] = urls[-1]
    return bibliography


def _source_url(source: object) -> str:
    if not isinstance(source, dict):
        return ""
    return _normalize_url(str(source.get("url") or ""))


def _source_title(source: object) -> str:
    if not isinstance(source, dict):
        return ""
    return str(source.get("title") or "").strip()


def _source_positions_by_url(sources: list[object]) -> dict[str, list[int]]:
    positions: defaultdict[str, list[int]] = defaultdict(list)
    for position, source in enumerate(sources):
        url = _source_url(source)
        if url:
            positions[url].append(position)
    return dict(positions)


def _is_importable_source(source: object) -> bool:
    """Return whether core import_research_sources can import this source.

    The research task outputs the final Deep Report as a pseudo-source in the results,
    but it cannot be imported back into the notebook.
    """
    if not isinstance(source, dict):
        return True
    return bool(source.get("url")) and source.get("result_type") != RESULT_TYPE_DEEP_REPORT


def _derive_cited_source_positions(report: str, sources: list[object]) -> set[int]:
    """Resolve report citations to source list positions."""
    if not report or not sources:
        return set()

    url_to_positions = _source_positions_by_url(sources)
    strong_positions: set[int] = set()
    bibliography = _parse_bibliography_urls(report)

    for citation_number in _parse_citation_numbers(report):
        url = bibliography.get(citation_number)
        if url:
            strong_positions.update(url_to_positions.get(url, []))

    for url in _extract_urls(report):
        strong_positions.update(url_to_positions.get(url, []))

    cited_positions = set(strong_positions)
    report_lower = report.lower()
    title_to_positions: defaultdict[str, list[int]] = defaultdict(list)
    for position, source in enumerate(sources):
        title = _source_title(source).lower()
        if len(title) >= 8:
            title_to_positions[title].append(position)

    for title, positions in title_to_positions.items():
        # Use whitespace/boundary anchors to prevent substring false positives
        # (e.g. "analysis" matching inside "psychoanalysis"). We avoid \b because
        # it fails when titles start or end with non-word characters like ( ) [ ].
        pattern = rf"(?:^|\s){re.escape(title)}(?:\s|$)"
        if re.search(pattern, report_lower) and not any(
            position in strong_positions for position in positions
        ):
            cited_positions.update(positions)

    return cited_positions


def annotate_cited_sources(sources: list[object], report: str) -> list[object]:
    """Return sources with a `cited` flag derived from the research report."""
    cited_positions = _derive_cited_source_positions(report, sources)
    annotated_sources: list[object] = []
    for position, source in enumerate(sources):
        if isinstance(source, dict):
            annotated_source = dict(source)
            annotated_source["cited"] = position in cited_positions
            annotated_sources.append(annotated_source)
        else:
            annotated_sources.append(source)
    return annotated_sources


def start_research(
    client: NotebookLMClient,
    notebook_id: str,
    query: str,
    source: str = "web",
    mode: str = "fast",
) -> ResearchStartResult:
    """Start a research task to find new sources.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        query: What to search for
        source: "web" or "drive"
        mode: "fast" (~30s) or "deep" (~5min, web only)

    Returns:
        ResearchStartResult with task details

    Raises:
        ValidationError: If source, mode, or combination is invalid
        ServiceError: If the API call fails
    """
    if source not in VALID_SOURCES:
        raise ValidationError(
            f"Invalid source '{source}'. Must be one of: {', '.join(VALID_SOURCES)}",
        )

    if mode not in VALID_MODES:
        raise ValidationError(
            f"Invalid mode '{mode}'. Must be one of: {', '.join(VALID_MODES)}",
        )

    if mode == "deep" and source != "web":
        raise ValidationError(
            "Deep research mode is only available for web sources.",
            user_message="Deep research is web-only. Use --mode fast for Drive search.",
        )

    if not query or not query.strip():
        raise ValidationError(
            "Query is required for research.",
            user_message="Please provide a search query.",
        )

    try:
        result = client.start_research(
            notebook_id=notebook_id,
            query=query,
            source=source,
            mode=mode,
        )
    except RPCError as e:
        # Structured API error (e.g., DeepResearchErrorDetail)
        short_detail = e.detail_type.rsplit(".", 1)[-1] if e.detail_type else "unknown"
        raise ServiceError(
            f"Google API error code {e.error_code} ({short_detail})",
            user_message=(
                f"Failed to start research — Google API error code {e.error_code} ({short_detail}).\n"
                f"This is likely a transient issue. Try again in a few minutes, or use --mode fast."
            ),
        ) from e
    except RPCDriftError as e:
        # Let the actionable NOTEBOOKLM_RPC_OVERRIDES guidance reach the user verbatim.
        raise ServiceError(message=str(e), user_message=str(e)) from e
    except Exception as e:
        raise ServiceError(f"Failed to start research: {e}") from e

    if result:
        return {
            "task_id": result.get("task_id", ""),
            "notebook_id": result.get("notebook_id", notebook_id),
            "query": query,
            "source": source,
            "mode": mode,
            "message": "Research started. Use research_status to check progress.",
        }

    raise ServiceError(
        "Research start returned no data",
        user_message="Failed to start research — no confirmation from API.",
    )


def poll_research(
    client: NotebookLMClient,
    notebook_id: str,
    task_id: str | None = None,
    query: str | None = None,
    compact: bool = True,
    poll_interval: int = 30,
    max_wait: int = 0,
    auto_import: bool = False,
    no_research_grace: float = NO_RESEARCH_GRACE_SECONDS,
) -> ResearchStatusResult:
    """Poll research progress, optionally blocking until complete or timeout.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        task_id: Specific task ID to poll
        query: Query text for fallback matching
        compact: Truncate report and limit sources
        poll_interval: Seconds between polls (default: 30)
        max_wait: Max seconds to wait (default: 0 = single check).
            When > 0, polls repeatedly until status is "completed" or
            the timeout is reached.
        auto_import: Import at most once per profile/notebook/original task ID via
            a durable claim. Requires explicit task_id to survive provider ID
            mutations. Unknown outcomes block replay until reconciliation.
        no_research_grace: Seconds to keep retrying when the poll comes back empty
            for a known task_id (a task started moments ago may not be visible
            yet). Only applies while blocking (max_wait > 0) with a task_id, and
            never extends past max_wait. 0 disables the grace period.

    Returns:
        ResearchStatusResult with current status. Note that the returned `sources`
        are annotated with a `cited` boolean flag derived from the report.

    Raises:
        ServiceError: If the poll fails
    """
    blocking = max_wait > 0
    started = time.monotonic() if blocking else 0
    deadline = started + max_wait if blocking else 0

    while True:
        try:
            result = client.poll_research(
                notebook_id=notebook_id,
                target_task_id=task_id,
                target_query=query,
            )
        except Exception as e:
            raise ServiceError(f"Failed to poll research: {e}") from e

        # Right after `research start`, the task may not be visible to the poll RPC
        # yet. Retry for a short, bounded grace period instead of giving up (#346).
        if (
            blocking
            and task_id
            and no_research_grace > 0
            and (not result or result.get("status") == "no_research")
        ):
            now = time.monotonic()
            budget = min(deadline - now, started + no_research_grace - now)
            if budget > 0:
                retry_interval = min(NO_RESEARCH_RETRY_INTERVAL, max(poll_interval, 1))
                time.sleep(min(retry_interval, budget))
                continue

        if not result:
            return {
                "status": "no_research",
                "notebook_id": notebook_id,
                "task_id": None,
                "sources_found": 0,
                "sources": [],
                "report": "",
                "message": None,
            }

        status = result.get("status", "unknown")

        # If completed or not blocking, format and return immediately
        if status != "in_progress" or deadline == 0:
            break

        # Still in progress — sleep and retry if time remains
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    report = result.get("report", "")
    sources = annotate_cited_sources(result.get("sources", []), report)

    if compact:
        if len(report) > 500:
            report = report[:500] + "...[truncated]"
        if len(sources) > 5:
            total = len(sources)
            sources = sources[:5]
            sources.append({"note": f"...and {total - 5} more sources"})

    completed_task_id = result.get("task_id") if status == "completed" else None

    imported: bool | None = False
    import_state = "not_requested" if not auto_import else "not_attempted"
    import_error = None
    if auto_import and status == "completed":
        # Only the caller's original task ID is stable across deep-research
        # provider task-ID changes. Never auto-import without that binding.
        if not isinstance(task_id, str) or not task_id.strip():
            imported = None
            import_state = "guard_unavailable"
            import_error = "import_task_identity_required"
        elif not isinstance(completed_task_id, str) or completed_task_id != task_id:
            # Core polling can fall back to a different task when the provider
            # mutates IDs. That fallback is acceptable for display, never for
            # a non-idempotent import of an unproven task.
            imported = None
            import_state = "guard_unavailable"
            import_error = "import_task_mismatch"
        else:
            imported, import_state, import_error = import_once(
                client,
                notebook_id,
                task_id,
                lambda: import_research(client, notebook_id, task_id),
            )

    response = {
        "status": status,
        "notebook_id": notebook_id,
        "task_id": result.get("task_id"),
        "sources_found": len(result.get("sources", [])),
        "sources": sources,
        "report": report,
        "imported": imported if auto_import else None,
        "import_state": import_state,
        "message": "Use research_import to add sources to notebook."
        if (status == "completed" and not auto_import)
        else None,
        "next_action": (
            f"Call research_import(notebook_id={notebook_id!r}, "
            f"task_id={completed_task_id!r}) to add the sources to the notebook."
            if (completed_task_id and not auto_import)
            else None
        ),
    }
    if import_error is not None:
        response["import_error"] = import_error
        if import_error == "import_task_identity_required":
            response["message"] = "Automatic import skipped: original task ID is required."
            response["next_action"] = (
                "Pass the original research_start task_id to research_status "
                "with auto_import=True; check existing notebook sources first."
            )
        elif import_error == "import_task_mismatch":
            response["message"] = "Automatic import blocked: provider task identity changed."
            response["next_action"] = (
                "Confirm the original-to-provider research task association before "
                "using the explicitly requested manual import; do not auto-retry."
            )
        else:
            response["message"] = (
                "Research completed, but automatic source import was not confirmed."
            )
            response["next_action"] = (
                "Check the notebook source list and reconcile existing source IDs "
                "before manually attempting another import."
            )
    return response


def import_research(
    client: NotebookLMClient,
    notebook_id: str,
    task_id: str,
    source_indices: list[int] | None = None,
    timeout: float = 300.0,
    cited_only: bool = False,
) -> ResearchImportResult:
    """Import discovered sources from a completed research task.

    Args:
        client: Authenticated NotebookLM client
        notebook_id: Notebook UUID
        task_id: Research task ID
        source_indices: Indices of sources to import (default: all)
        timeout: HTTP timeout in seconds (default: 300s)
        cited_only: Import only sources cited by the research report.
            Overrides source_indices when enabled.

    Returns:
        ResearchImportResult

    Raises:
        ServiceError: If import fails or no sources available
    """
    try:
        research_result = client.poll_research(
            notebook_id=notebook_id,
            target_task_id=task_id,
        )
    except Exception as e:
        raise ServiceError(f"Failed to retrieve research results: {e}") from e

    if not research_result or research_result.get("status") == "no_research":
        raise ServiceError(
            "Research task not found or not completed.",
            user_message="Research task not found. Ensure the task has completed.",
        )

    all_sources = research_result.get("sources", [])
    if not all_sources:
        raise ServiceError(
            "No sources found in research results.",
            user_message="No sources were found in the research results.",
        )

    if cited_only:
        cited_positions = _derive_cited_source_positions(
            research_result.get("report", ""),
            all_sources,
        )
        cited_sources = [
            source for position, source in enumerate(all_sources) if position in cited_positions
        ]
        sources_to_import = (
            cited_sources
            if cited_sources and any(_is_importable_source(source) for source in cited_sources)
            else all_sources
        )
    elif source_indices is not None:
        sources_to_import = [
            all_sources[idx] for idx in source_indices if 0 <= idx < len(all_sources)
        ]
    else:
        sources_to_import = all_sources

    if not sources_to_import:
        raise ValidationError(
            "No valid source indices provided.",
            user_message="None of the specified indices matched available sources.",
        )

    try:
        result = client.import_research_sources(
            notebook_id=notebook_id,
            task_id=research_result.get("task_id", task_id),
            sources=sources_to_import,
            timeout=timeout,
        )
    except Exception as e:
        raise ServiceError(f"Failed to import sources: {e}") from e

    if result:
        return {
            "notebook_id": notebook_id,
            "imported_count": len(result),
            "imported_sources": result,
            "message": f"Imported {len(result)} sources.",
        }

    raise ServiceError(
        "Source import returned no data",
        user_message="Failed to import sources — no confirmation from API.",
    )
