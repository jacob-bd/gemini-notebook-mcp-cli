"""CSRF extraction failure must not persist an authenticated HTML page."""

import httpx
import pytest

from notebooklm_tools.core import base


class _FakeResponse:
    url = "https://notebook.google.com/"
    status_code = 200
    text = "<html>no csrf token anywhere in here</html>"


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *args, **kwargs):
        return _FakeResponse()


def test_csrf_failure_does_not_write_authenticated_html(tmp_path, monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(base.BaseClient, "_get_httpx_cookies", lambda self: {})
    monkeypatch.setattr(
        "notebooklm_tools.core.cookie_rotation.rotate_google_cookies", lambda c: None
    )
    monkeypatch.setattr("notebooklm_tools.utils.config.get_storage_dir", lambda: tmp_path)

    client = base.BaseClient.__new__(base.BaseClient)
    monkeypatch.setattr(type(client), "_get_base_url", lambda self: "https://notebook.google.com")
    monkeypatch.setattr(type(client), "_is_enterprise", lambda self: False)

    with pytest.raises(ValueError, match="no HTML was saved"):
        client._refresh_auth_tokens()

    assert not (tmp_path / "debug_page.html").exists()
