"""Tests for the usage service.

Fixtures are trimmed copies of real `EylDcb` responses captured from the live
API, including one where the two windows arrive in the opposite order.
"""

import pytest

from notebooklm_tools.core.usage import UsageMixin, _find_tier
from notebooklm_tools.services.errors import ServiceError
from notebooklm_tools.services.usage import get_usage

# Weekly window partly consumed, rolling window untouched. Rolling arrives first.
USAGE_ROLLING_FIRST = [
    1,
    [
        [None, None, None, None, 1, [1789200870, 16877000], None, 100],
        [None, None, None, None, 2, [1789697670, 16986000], 8.703406947222222, 91.29659305277778],
    ],
    None,
    [[1, True, 6, 3, 1, 11.177083333333334]],
]

# The same account, same call, with the windows in the opposite order. The API
# does not guarantee ordering, so the service must key on the window type code.
USAGE_WEEKLY_FIRST = [
    1,
    [
        [None, None, None, None, 2, [1789697670, 16986000], 8.703406947222222, 91.29659305277778],
        [None, None, None, None, 1, [1789200870, 16877000], None, 100],
    ],
    None,
    [],
]

ENTITLEMENT = [[[[None, "1", 1469], None, 1386, "NOTEBOOKLM_TIER_PRO_CONSUMER_USER", False]]]


class FakeClient(UsageMixin):
    """Exercises the real mixin parsing against canned RPC responses."""

    def __init__(self, usage_payload, entitlement_payload=ENTITLEMENT, usage_error=None):
        self._usage_payload = usage_payload
        self._entitlement_payload = entitlement_payload
        self._usage_error = usage_error

    def _call_rpc(self, rpc_id, params, *args, **kwargs):
        if rpc_id == self.RPC_GET_USAGE:
            if self._usage_error:
                raise self._usage_error
            return self._usage_payload
        if rpc_id == self.RPC_GET_ENTITLEMENT:
            if isinstance(self._entitlement_payload, Exception):
                raise self._entitlement_payload
            return self._entitlement_payload
        raise AssertionError(f"unexpected rpc {rpc_id}")


def _by_window(result):
    return {w["window"]: w for w in result["windows"]}


def test_reports_both_windows_with_percentages_and_reset_times():
    result = get_usage(FakeClient(USAGE_ROLLING_FIRST))
    windows = _by_window(result)

    assert set(windows) == {"rolling", "weekly"}
    assert windows["weekly"]["percent_used"] == pytest.approx(8.7034069, rel=1e-6)
    assert windows["weekly"]["percent_remaining"] == pytest.approx(91.2965930, rel=1e-6)
    assert windows["weekly"]["resets_at"] == "2026-09-18T02:14:30+00:00"
    assert result["tier"] == "NOTEBOOKLM_TIER_PRO_CONSUMER_USER"


def test_window_identity_survives_reordering():
    """The API reorders these entries, so position must never identify a window."""
    first = _by_window(get_usage(FakeClient(USAGE_ROLLING_FIRST)))
    second = _by_window(get_usage(FakeClient(USAGE_WEEKLY_FIRST)))

    assert first["weekly"] == second["weekly"]
    assert first["rolling"] == second["rolling"]
    # The bug this guards against: reading by position swaps the two budgets.
    assert first["weekly"]["percent_remaining"] != first["rolling"]["percent_remaining"]


def test_absent_used_percentage_is_zero_only_when_allowance_is_full():
    windows = _by_window(get_usage(FakeClient(USAGE_ROLLING_FIRST)))
    assert windows["rolling"]["percent_used"] == 0.0
    assert windows["rolling"]["percent_remaining"] == 100


def test_absent_used_percentage_stays_unknown_when_allowance_is_partial():
    payload = [1, [[None, None, None, None, 1, [1789200870, 0], None, 55.0]], None, []]
    windows = _by_window(get_usage(FakeClient(payload)))
    assert windows["rolling"]["percent_used"] is None
    assert windows["rolling"]["percent_remaining"] == 55.0


def test_authentication_failure_is_raised_not_reported_as_quota():
    """An expired session must never look like an exhausted allowance."""
    client = FakeClient(None, usage_error=RuntimeError("Authentication expired"))
    with pytest.raises(ServiceError) as excinfo:
        get_usage(client)
    assert "auth refresh" in (excinfo.value.hint or "")


def test_empty_window_list_raises():
    with pytest.raises(ServiceError):
        get_usage(FakeClient([1, [], None, []]))


def test_malformed_payload_raises():
    with pytest.raises(ServiceError):
        get_usage(FakeClient(["unexpected"]))


def test_tier_failure_does_not_deny_usage_figures():
    client = FakeClient(USAGE_ROLLING_FIRST, entitlement_payload=RuntimeError("boom"))
    result = get_usage(client)
    assert result["tier"] is None
    assert len(result["windows"]) == 2


def test_find_tier_ignores_unrelated_strings():
    assert _find_tier([["Manage subscription", ["CAI="]]]) is None
    assert _find_tier([[["NOTEBOOKLM_TIER_FREE_USER"]]]) == "NOTEBOOKLM_TIER_FREE_USER"


def test_output_order_is_stable_regardless_of_api_order():
    """The API reorders its entries; the reported order must not follow it."""
    rolling_first = [w["window"] for w in get_usage(FakeClient(USAGE_ROLLING_FIRST))["windows"]]
    weekly_first = [w["window"] for w in get_usage(FakeClient(USAGE_WEEKLY_FIRST))["windows"]]

    assert rolling_first == weekly_first == ["rolling", "weekly"]
