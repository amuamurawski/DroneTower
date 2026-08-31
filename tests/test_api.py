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
from custom_components.dronetower_amu.const import (
    CHECKINS_ENDPOINT,
    KEYCLOAK_TOKEN_ENDPOINT,
)

NUL = "\x00"

TOKEN_RESPONSE = {
    "access_token": "tok",
    "expires_in": 300,
    "refresh_token": "rt",
}


async def test_login_then_checkins_sends_bearer_token(hass, aioclient_mock):
    aioclient_mock.post(KEYCLOAK_TOKEN_ENDPOINT, json=TOKEN_RESPONSE)
    aioclient_mock.get(
        CHECKINS_ENDPOINT, json={"checkins": [{"id": "a"}, "junk", {"id": "b"}]}
    )

    client = DroneTowerClient(async_get_clientsession(hass), "pilot@example.com", "pw")
    checkins = await client.async_get_checkins()

    assert [c["id"] for c in checkins] == ["a", "b"]
    # The password grant carries the credentials, not the checkins request.
    post_call = next(c for c in aioclient_mock.mock_calls if c[0].upper() == "POST")
    assert post_call[2]["grant_type"] == "password"
    assert post_call[2]["username"] == "pilot@example.com"
    get_call = next(c for c in aioclient_mock.mock_calls if c[0].upper() == "GET")
    assert get_call[3]["Authorization"] == "Bearer tok"


async def test_login_rejects_bad_credentials(hass, aioclient_mock):
    aioclient_mock.post(KEYCLOAK_TOKEN_ENDPOINT, status=401)

    client = DroneTowerClient(async_get_clientsession(hass), "pilot@example.com", "bad")
    with pytest.raises(DroneTowerAuthError):
        await client.async_login()


async def test_checkins_without_credentials_raises_auth(hass, aioclient_mock):
    client = DroneTowerClient(async_get_clientsession(hass))
    with pytest.raises(DroneTowerAuthError):
        await client.async_get_checkins()


async def test_expired_token_is_refreshed_on_401(hass, aioclient_mock):
    aioclient_mock.post(
        KEYCLOAK_TOKEN_ENDPOINT,
        json={"access_token": "fresh", "expires_in": 300, "refresh_token": "rt2"},
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

    client = DroneTowerClient(async_get_clientsession(hass), "pilot@example.com", "pw")
    client._token = "stale"
    client._refresh_token = "rt"

    checkins = await client.async_get_checkins()

    assert [c["id"] for c in checkins] == ["z"]
    assert calls["n"] == 2
    # Exactly one token exchange, and it used the refresh grant.
    posts = [c for c in aioclient_mock.mock_calls if c[0].upper() == "POST"]
    assert len(posts) == 1
    assert posts[0][2]["grant_type"] == "refresh_token"


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
