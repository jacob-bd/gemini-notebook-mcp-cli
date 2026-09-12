"""Usage tools - plan allowance windows and subscription tier."""

from ...services import ServiceError
from ...services import usage as usage_service
from ._utils import ResultDict, error_result, get_client, logged_tool


@logged_tool()
def usage_get() -> ResultDict:
    """Show how much of the plan's usage allowance is left, and when it resets.

    Gemini Notebook meters usage as compute against two windows at once: a short
    rolling window and a weekly one. Both are reported, each with the percentage
    used, the percentage remaining and the reset time in UTC.
    """
    try:
        client = get_client()
        result = usage_service.get_usage(client)
        return {"status": "success", **result}
    except ServiceError as e:
        return error_result(e.user_message, hint=e.hint)
    except Exception as e:
        return error_result(str(e))
