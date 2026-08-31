"""Unit tests for the STOMP frame handling and the REST authentication."""

from __future__ import annotations

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.dronetower_amu.api import (
    DroneTowerAuthError,
    DroneTowerClient,
    _parse_frame,
    _unescape,
)
from custom_components.dronetower_amu.const import CHECKINS_ENDPOINT

NUL = "\x00"


class _FakeCurlResponse:
    """Stand-in for a curl_cffi response."""

    def __init__(self, status_code: int, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_data or {}

    def json(self) -> dict:
        return self._json


class _FakeCurlSession:
    """Patches api.CurlAsyncSession: records posts, returns queued responses."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self._queue: list[_FakeCurlResponse] = []

    def queue(self, status: int, json_data: dict | None = None) -> "_FakeCurlSession":
        self._queue.append(_FakeCurlResponse(status, json_data))
        return self

    async def __aenter__(self) -> "_FakeCurlSession":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, url, **kwargs):
        self.posts.append(kwargs)
        return self._queue.pop(0)


def _patch_curl(fake: _FakeCurlSession):
    from unittest.mock import patch

    return patch(
        "custom_components.dronetower_amu.api.CurlAsyncSession", return_value=fake
    )


async def test_login_then_checkins_sends_bearer_token(hass, aioclient_mock):
    fake = _FakeCurlSession().queue(
        200, {"access_token": "tok", "expires_in": 300, "refresh_token": "rt"}
    )
    aioclient_mock.get(
        CHECKINS_ENDPOINT, json={"checkins": [{"id": "a"}, "junk", {"id": "b"}]}
    )

    with _patch_curl(fake):
        client = DroneTowerClient(
            async_get_clientsession(hass), "pilot@example.com", "pw"
        )
        checkins = await client.async_get_checkins()

    assert [c["id"] for c in checkins] == ["a", "b"]
    # The password grant (via curl_cffi) carries the credentials; the checkins request
    # carries the bearer token.
    assert fake.posts[0]["data"]["grant_type"] == "password"
    assert fake.posts[0]["data"]["username"] == "pilot@example.com"
    assert fake.posts[0]["impersonate"] == "chrome"
    get_call = next(c for c in aioclient_mock.mock_calls if c[0].upper() == "GET")
    assert get_call[3]["Authorization"] == "Bearer tok"


async def test_login_rejects_bad_credentials(hass):
    fake = _FakeCurlSession().queue(401, {"error": "invalid_grant"})

    with _patch_curl(fake):
        client = DroneTowerClient(
            async_get_clientsession(hass), "pilot@example.com", "bad"
        )
        with pytest.raises(DroneTowerAuthError):
            await client.async_login()


async def test_checkins_without_credentials_raises_auth(hass):
    client = DroneTowerClient(async_get_clientsession(hass))
    with pytest.raises(DroneTowerAuthError):
        await client.async_get_checkins()


async def test_expired_token_is_refreshed_on_401(hass, aioclient_mock):
    fake = _FakeCurlSession().queue(
        200, {"access_token": "fresh", "expires_in": 300, "refresh_token": "rt2"}
    )

    # First GET is rejected as if the cached token had expired; the retry succeeds.
    calls = {"n": 0}

    async def flip(method, url, data):
        calls["n"] += 1
        if calls["n"] == 1:
            return AiohttpClientMockResponse(method, URL(CHECKINS_ENDPOINT), status=401)
        return AiohttpClientMockResponse(
            method, URL(CHECKINS_ENDPOINT), json={"checkins": [{"id": "z"}]}
        )

    aioclient_mock.get(CHECKINS_ENDPOINT, side_effect=flip)

    with _patch_curl(fake):
        client = DroneTowerClient(
            async_get_clientsession(hass), "pilot@example.com", "pw"
        )
        client._token = "stale"
        client._refresh_token = "rt"
        checkins = await client.async_get_checkins()

    assert [c["id"] for c in checkins] == ["z"]
    assert calls["n"] == 2
    # Exactly one token exchange, and it used the refresh grant.
    assert len(fake.posts) == 1
    assert fake.posts[0]["data"]["grant_type"] == "refresh_token"


def test_parse_connected_frame():
    command, headers, body = _parse_frame(
        "CONNECTED\nversion:1.2\nheart-beat:5000,5000\n\n"
    )
    assert command == "CONNECTED"
    assert headers["version"] == "1.2"
    assert headers["heart-beat"] == "5000,5000"
    assert body == ""


def test_parse_message_frame_keeps_event_type_header():
    raw = (
        "MESSAGE\n"
        "event-type:CheckinEvent\n"
        "destination:/websocket/topic/x\n"
        "content-type:text/plain;charset=UTF-8\n"
        "subscription:sub-0\n"
        "content-length:20\n"
        "\n"
        '{"checkin":{"id":1}}'
    )
    command, headers, body = _parse_frame(raw)
    assert command == "MESSAGE"
    assert headers["event-type"] == "CheckinEvent"
    assert body == '{"checkin":{"id":1}}'


def test_parse_frame_ignores_heartbeat_and_padding():
    assert _parse_frame("\n") is None
    assert _parse_frame("") is None
    assert _parse_frame("\n\n\r") is None


def test_parse_frame_tolerates_leading_heartbeat():
    command, _, _ = _parse_frame("\nMESSAGE\nevent-type:CheckinEvent\n\nbody")
    assert command == "MESSAGE"


def test_repeated_header_keeps_first_occurrence():
    _, headers, _ = _parse_frame("MESSAGE\nx:first\nx:second\n\n")
    assert headers["x"] == "first"


def test_header_unescaping():
    assert _unescape(r"a\cb") == "a:b"
    assert _unescape(r"a\nb") == "a\nb"
    assert _unescape(r"a\\b") == "a\\b"
