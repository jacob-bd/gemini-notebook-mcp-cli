"""Usage service — plan allowance windows and subscription tier.

Gemini Notebook meters usage as compute against two simultaneous windows: a
short rolling window and a weekly one. The backend reports what is left in each
and when it resets, so this service reports measured values and never estimates
the cost of a prompt.
"""

from datetime import UTC, datetime

from ..core.client import NotebookLMClient
from ..core.usage import USAGE_WINDOW_ROLLING, USAGE_WINDOW_WEEKLY
from .errors import ServiceError

_WINDOW_NAMES = {
    USAGE_WINDOW_ROLLING: "rolling",
    USAGE_WINDOW_WEEKLY: "weekly",
}

# The backend returns the windows in an unstable order, so output is sorted to
# keep it deterministic for anyone parsing it. Shortest window first, since that
# is the one that blocks work soonest. Unknown windows sort last.
_WINDOW_ORDER = ["rolling", "weekly"]


def _to_iso(epoch_seconds: int | None) -> str | None:
    """Convert epoch seconds to an ISO 8601 UTC string."""
    if epoch_seconds is None:
        return None
    try:
        return datetime.fromtimestamp(epoch_seconds, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _shape_window(raw: dict) -> dict:
    """Normalize one raw window entry into the reported shape.

    ``percent_used`` is absent rather than zero when nothing has been consumed,
    so it is normalized to 0.0 only when the remaining percentage confirms a
    full allowance. Anything else is reported as None, which callers must read
    as unknown rather than as zero.
    """
    remaining = raw.get("percent_remaining")
    used = raw.get("percent_used")

    if used is None and remaining == 100:
        used = 0.0

    return {
        "window": _WINDOW_NAMES.get(raw.get("window"), "unknown"),
        "percent_used": used,
        "percent_remaining": remaining,
        "resets_at": _to_iso(raw.get("resets_at")),
    }


def get_usage(client: NotebookLMClient) -> dict:
    """Report the remaining allowance for each usage window, plus the plan tier.

    The tier is best-effort: a failure to read it must not deny the caller the
    usage figures, which are the part that governs whether work can proceed.

    Returns a dict with:
        - windows: list of window dicts, each with window, percent_used,
          percent_remaining and resets_at (ISO 8601 UTC)
        - tier: the subscription tier string, or None when unavailable
    """
    try:
        raw_windows = client.get_usage()
    except Exception as e:
        # An expired session surfaces here as an authentication error. Callers
        # must be able to tell that apart from an exhausted allowance, so the
        # failure is reported as-is rather than as a quota result.
        raise ServiceError(
            f"Failed to read usage: {e}",
            user_message=f"Could not read plan usage — {e}",
            hint="If this is an authentication error, run 'nlm auth refresh' or 'nlm login'.",
        ) from e

    if not raw_windows:
        raise ServiceError(
            "Usage response contained no windows",
            user_message="Gemini Notebook returned no usage information.",
            hint="The response shape may have changed. Re-run with --debug to inspect it.",
        )

    try:
        tier = client.get_entitlement_tier()
    except Exception:
        tier = None

    windows = [_shape_window(w) for w in raw_windows]
    windows.sort(
        key=lambda w: (
            _WINDOW_ORDER.index(w["window"]) if w["window"] in _WINDOW_ORDER else len(_WINDOW_ORDER)
        )
    )

    return {"windows": windows, "tier": tier}
