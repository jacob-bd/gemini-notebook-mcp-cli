"""Shared test fixtures."""

import pytest

from notebooklm_tools.core.cookie_rotation import DISABLE_ROTATE_COOKIES_ENV


@pytest.fixture(autouse=True)
def _isolate_storage(monkeypatch, tmp_path):
    """Point all storage (~/.notebooklm-mcp-cli) at a per-test temp dir.

    Several code paths (e.g. BaseClient._update_cached_tokens, headless auth)
    write to the real auth cache and Chrome profile. Without this guard, tests
    that exercise them corrupt the developer's real login (see
    test_refresh_auth_tokens_success, which used to overwrite auth.json with
    fake test tokens).
    """
    monkeypatch.setenv("NOTEBOOKLM_MCP_CLI_PATH", str(tmp_path / "storage"))


@pytest.fixture(autouse=True)
def _disable_cookie_rotation(monkeypatch):
    """Keep tests from hitting accounts.google.com.

    BaseClient._call_rpc rotates Google cookies before real RPC calls; a test
    with a mocked HTTP client could otherwise "succeed" at rotation against
    the mock. Tests that exercise rotation itself re-enable it with
    monkeypatch.delenv.
    """
    monkeypatch.setenv(DISABLE_ROTATE_COOKIES_ENV, "1")
