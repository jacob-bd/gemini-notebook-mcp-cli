from __future__ import annotations

import httpx

from notebooklm_tools.core.cookie_rotation import (
    DISABLE_ROTATE_COOKIES_ENV,
    ROTATE_COOKIES_BODY,
    ROTATE_COOKIES_URL,
    cookie_jar_to_dict,
    rotate_google_cookies,
)


def test_rotate_google_cookies_posts_expected_request(monkeypatch):
    monkeypatch.delenv(DISABLE_ROTATE_COOKIES_ENV, raising=False)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["body"] = request.content
        seen["origin"] = request.headers.get("origin")
        return httpx.Response(
            200,
            headers={"Set-Cookie": "__Secure-1PSIDTS=rotated; Domain=.google.com; Path=/; Secure"},
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        cookies=httpx.Cookies(),
    )

    result = rotate_google_cookies(client, force=True)

    assert result.attempted is True
    assert result.success is True
    assert seen == {
        "method": "POST",
        "url": ROTATE_COOKIES_URL,
        "body": ROTATE_COOKIES_BODY.encode(),
        "origin": "https://accounts.google.com",
    }
    assert cookie_jar_to_dict(client.cookies)["__Secure-1PSIDTS"] == "rotated"


def test_rotate_google_cookies_can_be_disabled(monkeypatch):
    monkeypatch.setenv(DISABLE_ROTATE_COOKIES_ENV, "1")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("RotateCookies request should not run")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    result = rotate_google_cookies(client, force=True)

    assert result.attempted is False
    assert result.success is False
    assert result.skipped_reason == f"{DISABLE_ROTATE_COOKIES_ENV}=1"


def test_cookie_jar_to_dict_prefers_google_com_value():
    cookies = httpx.Cookies()
    cookies.set("SID", "youtube", domain=".youtube.com")
    cookies.set("SID", "google", domain=".google.com")

    assert cookie_jar_to_dict(cookies)["SID"] == "google"
