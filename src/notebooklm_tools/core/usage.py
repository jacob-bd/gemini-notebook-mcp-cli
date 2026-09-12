"""UsageMixin - plan usage allowance and subscription tier.

Gemini Notebook replaced fixed daily caps with a compute-based allowance in
September 2026. Two windows apply at once: a short rolling window and a weekly
window. The backend reports the remaining percentage and the reset time for
both, so no client-side estimation of compute cost is needed.
"""

import logging

from .base import BaseClient

logger = logging.getLogger(__name__)

# Window type codes returned at index 4 of each usage entry.
USAGE_WINDOW_ROLLING = 1
USAGE_WINDOW_WEEKLY = 2

# Product ID the entitlement RPC is queried against, matching the value already
# recorded in docs/API_REFERENCE.md. The backend accepts more than one value
# here and returns the same tier for each (1469 was also observed working).
_ENTITLEMENT_PRODUCT_ID = 627


class UsageMixin(BaseClient):
    """Mixin for reading plan usage windows and subscription tier."""

    def _get_usage_header(self) -> list:
        """Returns the standard header these RPCs expect as their only param."""
        return [2, None, [1], [1, None, None, None, None, None, None, None, None, None, [1, 3]]]

    def get_usage(self) -> list[dict]:
        """Fetch the remaining allowance for every usage window.

        Returns:
            One dict per window, each with:
                - window: ``USAGE_WINDOW_ROLLING`` or ``USAGE_WINDOW_WEEKLY``
                - percent_used: float or None when nothing has been consumed
                - percent_remaining: float or None when the backend omits it
                - resets_at: reset time as epoch seconds (int), or None
        """
        result = self._call_rpc(self.RPC_GET_USAGE, [self._get_usage_header()])

        if not isinstance(result, list) or len(result) < 2 or not isinstance(result[1], list):
            logger.debug("Unexpected usage payload shape: %r", result)
            return []

        windows = []
        for entry in result[1]:
            # Entries are NOT returned in a stable order, so the window is
            # identified by its type code rather than by position.
            if not isinstance(entry, list) or len(entry) < 8:
                continue

            reset = entry[5]
            resets_at = reset[0] if isinstance(reset, list) and reset else None

            windows.append(
                {
                    "window": entry[4],
                    "percent_used": entry[6],
                    "percent_remaining": entry[7],
                    "resets_at": resets_at,
                }
            )

        return windows

    def get_entitlement_tier(self) -> str | None:
        """Fetch the subscription tier this account is entitled to.

        Returns:
            The tier string (for example ``NOTEBOOKLM_TIER_PRO_CONSUMER_USER``),
            or None when the backend returns no entitlement for the account.
        """
        params = [
            [
                [
                    [None, "1", _ENTITLEMENT_PRODUCT_ID],
                    [None, None, None, None, None, None, None, None, None, [None, None, 2]],
                    1,
                ]
            ]
        ]
        result = self._call_rpc(self.RPC_GET_ENTITLEMENT, params)
        return _find_tier(result)


def _find_tier(node: object, depth: int = 0) -> str | None:
    """Return the first tier string found anywhere in a decoded payload.

    The entitlement response nests the tier inside promotional and billing
    structures whose shape varies with the account's plan and offers, so the
    tier is located by its value rather than by a fixed index path.
    """
    if depth > 12:
        return None
    if isinstance(node, str):
        return node if node.startswith("NOTEBOOKLM_TIER_") else None
    if isinstance(node, list):
        for item in node:
            found = _find_tier(item, depth + 1)
            if found:
                return found
    return None
