from pathlib import Path

from notebooklm_tools.core.auth import AuthManager


def _write_cookies(tmp_path: Path) -> Path:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("SID=sid; HSID=h; SSID=s; APISID=a; SAPISID=sp", encoding="utf-8")
    return cookie_file


def test_login_with_file_records_rebranded_base_host(monkeypatch, tmp_path):
    """Manual cookie import must record the real session host.

    Google rolls the Gemini Notebook rebrand out per-account, redirecting
    notebooklm.google.com -> notebook.google.com. Otherwise valid cookies keep
    bouncing off the old host. See issue #292.
    """

    class FakeClient:
        def __init__(self, **kwargs):
            self.base_host = kwargs.get("base_host")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def list_notebooks(self):
            # Simulate the rebrand: only the rebranded host accepts the cookies.
            if self.base_host == "notebook.google.com":
                return []
            raise RuntimeError("auth rejected on legacy host")

    monkeypatch.setattr("notebooklm_tools.core.client.NotebookLMClient", FakeClient)

    manager = AuthManager("default")
    manager.profile_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = _write_cookies(tmp_path)

    manager.login_with_file(cookie_file)

    metadata = (manager.profile_dir / "metadata.json").read_text(encoding="utf-8")
    assert '"base_host": "notebook.google.com"' in metadata


def test_login_with_file_keeps_default_host_when_no_rebrand(monkeypatch, tmp_path):
    class FakeClient:
        def __init__(self, **kwargs):
            self.base_host = kwargs.get("base_host")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def list_notebooks(self):
            # Default host works: no rebrand for this account.
            if self.base_host == "notebooklm.google.com":
                return []
            raise RuntimeError("unexpected host probe")

    monkeypatch.setattr("notebooklm_tools.core.client.NotebookLMClient", FakeClient)

    manager = AuthManager("default")
    manager.profile_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = _write_cookies(tmp_path)

    manager.login_with_file(cookie_file)

    metadata = (manager.profile_dir / "metadata.json").read_text(encoding="utf-8")
    assert '"base_host": null' in metadata
