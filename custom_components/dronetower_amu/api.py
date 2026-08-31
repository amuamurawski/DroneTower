"""REST and STOMP-over-WebSocket client for the PANSA DroneTower BFF."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from .const import (
    CHECKINS_ENDPOINT,
    CONTENT_TYPE,
    KEYCLOAK_CLIENT_ID,
    KEYCLOAK_TOKEN_ENDPOINT,
    STOMP_PROTOCOLS,
    TOKEN_REFRESH_MARGIN,
    TOPIC_ACTIVE_CHECKINS,
    WS_HEARTBEAT_MS,
    WS_RECEIVE_TIMEOUT,
    WS_URL,
)

_LOGGER = logging.getLogger(__name__)

NUL = "\x00"

_UNESCAPE = (("\\r", "\r"), ("\\n", "\n"), ("\\c", ":"), ("\\\\", "\\"))


class DroneTowerError(Exception):
    """Raised when the DroneTower backend cannot be reached or refuses us."""


class DroneTowerAuthError(DroneTowerError):
    """Raised when the backend rejects our credentials or access token.

    Kept distinct from the base error so the coordinator can ask Home Assistant to
    re-prompt for a password (reauth) instead of quietly retrying forever.
    """


def _unescape(value: str) -> str:
    for escaped, plain in _UNESCAPE:
        value = value.replace(escaped, plain)
    return value


def _parse_frame(raw: str) -> tuple[str, dict[str, str], str] | None:
    """Parse one STOMP frame. Returns None for heartbeats and padding."""
    raw = raw.lstrip("\n\r")
    if not raw:
        return None
    head, _, body = raw.partition("\n\n")
    lines = head.split("\n")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            # STOMP keeps the first occurrence of a repeated header.
            headers.setdefault(_unescape(key), _unescape(value))
    return lines[0], headers, body


class DroneTowerClient:
    """Talks to the DroneTower backend the same way the mobile app does."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str | None = None,
        password: str | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._refresh_token: str | None = None
        # Monotonic deadline after which the access token must be renewed.
        self._token_expiry: float | None = None
        # Serialises token requests so a burst of 401s triggers one refresh, not a
        # stampede.
        self._login_lock = asyncio.Lock()

    @property
    def has_credentials(self) -> bool:
        return bool(self._email and self._password)

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": CONTENT_TYPE}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def async_login(self) -> None:
        """Sign in with the resource-owner password grant against PANSA's Keycloak.

        Raises DroneTowerAuthError when the credentials are refused (or none are
        configured), so the caller can start a reauth flow rather than retry.
        """
        if not self.has_credentials:
            raise DroneTowerAuthError("No DroneTower credentials configured")

        await self._token_request(
            {
                "grant_type": "password",
                "client_id": KEYCLOAK_CLIENT_ID,
                "scope": "openid",
                "username": self._email or "",
                "password": self._password or "",
            }
        )

    async def _async_refresh(self) -> None:
        """Renew the access token, falling back to a full login when needed."""
        if not self._refresh_token:
            await self.async_login()
            return
        try:
            await self._token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": KEYCLOAK_CLIENT_ID,
                    "refresh_token": self._refresh_token,
                }
            )
        except DroneTowerAuthError:
            # The refresh token has expired too; start over from the password.
            self._refresh_token = None
            await self.async_login()

    async def _token_request(self, data: dict[str, str]) -> None:
        """Run one Keycloak token exchange and store the result."""
        async with self._login_lock:
            try:
                # A dict body makes aiohttp send application/x-www-form-urlencoded and
                # set that header itself; do not set it by hand as well.
                async with self._session.post(
                    KEYCLOAK_TOKEN_ENDPOINT,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    # Keycloak answers a bad password or a dead refresh token with an
                    # invalid_grant at 400/401.
                    if response.status in (400, 401):
                        raise DroneTowerAuthError("DroneTower rejected the credentials")
                    if response.status == 429:
                        raise DroneTowerError("Rate limited by the DroneTower backend")
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except TimeoutError as err:
                raise DroneTowerError("Timeout authenticating with DroneTower") from err
            except aiohttp.ClientError as err:
                raise DroneTowerError(
                    f"DroneTower authentication failed: {err}"
                ) from err

            token = payload.get("access_token") if isinstance(payload, dict) else None
            if not token:
                raise DroneTowerError("DroneTower returned no access token")

            self._token = token
            self._refresh_token = payload.get("refresh_token") or self._refresh_token
            expires_in = payload.get("expires_in")
            self._token_expiry = (
                time.monotonic() + expires_in
                if isinstance(expires_in, (int, float))
                else None
            )

    async def _async_ensure_token(self) -> None:
        """Make sure a usable access token is in hand before a request."""
        if self._token is None:
            await self.async_login()
        elif (
            self._token_expiry is not None
            and time.monotonic() >= self._token_expiry - TOKEN_REFRESH_MARGIN
        ):
            await self._async_refresh()

    async def async_get_checkins(self) -> list[dict[str, Any]]:
        """Fetch the nationwide snapshot of active check-ins.

        Signs in on first use, refreshes proactively as the token nears expiry, and
        renews once reactively if the backend still rejects it.
        """
        await self._async_ensure_token()

        # Two passes at most: the second only after renewing the token on a 401.
        for attempt in range(2):
            try:
                async with self._session.get(
                    CHECKINS_ENDPOINT,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status in (401, 403):
                        if attempt == 0:
                            await self._async_refresh()
                            continue
                        raise DroneTowerAuthError(
                            "DroneTower rejected the access token"
                        )
                    if response.status == 429:
                        raise DroneTowerError("Rate limited by the DroneTower backend")
                    response.raise_for_status()
                    # The response advertises the vendor media type, not JSON.
                    payload = await response.json(content_type=None)
            except TimeoutError as err:
                raise DroneTowerError("Timeout talking to DroneTower") from err
            except aiohttp.ClientError as err:
                raise DroneTowerError(f"DroneTower request failed: {err}") from err

            if not isinstance(payload, dict):
                raise DroneTowerError("Unexpected response shape from /api/checkins")

            return [c for c in payload.get("checkins") or [] if isinstance(c, dict)]

        raise DroneTowerAuthError("DroneTower rejected the access token")

    async def async_run_stream(
        self,
        on_event: Callable[[str, dict[str, Any]], None],
        on_connected: Callable[[], None] | None = None,
    ) -> None:
        """Subscribe to the live check-in feed until the connection drops.

        Returns normally only if the server closes the socket; every other failure
        raises DroneTowerError so the caller can back off and retry.

        The broadcast feed connects anonymously, exactly as the app does: it sets no
        STOMP-level credentials and leans on the login session cookie, which rides
        along on this shared session's handshake if the broker ever starts asking.
        """
        try:
            async with self._session.ws_connect(
                WS_URL,
                protocols=STOMP_PROTOCOLS,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as websocket:
                await self._run_session(websocket, on_event, on_connected)
        except TimeoutError as err:
            raise DroneTowerError("WebSocket timed out") from err
        except aiohttp.ClientError as err:
            raise DroneTowerError(f"WebSocket failed: {err}") from err

    async def _run_session(
        self,
        websocket: aiohttp.ClientWebSocketResponse,
        on_event: Callable[[str, dict[str, Any]], None],
        on_connected: Callable[[], None] | None,
    ) -> None:
        await websocket.send_str(
            "CONNECT\n"
            "accept-version:1.0,1.1,1.2\n"
            f"heart-beat:{WS_HEARTBEAT_MS},{WS_HEARTBEAT_MS}\n"
            f"\n{NUL}"
        )

        heartbeat = asyncio.create_task(self._heartbeat(websocket))
        buffer = ""
        try:
            while True:
                message = await websocket.receive(timeout=WS_RECEIVE_TIMEOUT)

                if message.type is aiohttp.WSMsgType.TEXT:
                    buffer += message.data
                elif message.type is aiohttp.WSMsgType.BINARY:
                    buffer += message.data.decode("utf-8", "replace")
                elif message.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSING,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    raise DroneTowerError("WebSocket closed by the server")
                elif message.type is aiohttp.WSMsgType.ERROR:
                    raise DroneTowerError(f"WebSocket error: {websocket.exception()}")
                else:
                    continue

                while NUL in buffer:
                    raw, _, buffer = buffer.partition(NUL)
                    frame = _parse_frame(raw)
                    if frame is None:
                        continue
                    await self._handle_frame(
                        websocket, frame, on_event, on_connected
                    )
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _handle_frame(
        self,
        websocket: aiohttp.ClientWebSocketResponse,
        frame: tuple[str, dict[str, str], str],
        on_event: Callable[[str, dict[str, Any]], None],
        on_connected: Callable[[], None] | None,
    ) -> None:
        command, headers, body = frame

        if command == "CONNECTED":
            await websocket.send_str(
                "SUBSCRIBE\n"
                "id:sub-0\n"
                f"destination:{TOPIC_ACTIVE_CHECKINS}\n"
                f"\n{NUL}"
            )
            _LOGGER.debug("Subscribed to the DroneTower check-in broadcast")
            if on_connected is not None:
                on_connected()
            return

        if command == "ERROR":
            raise DroneTowerError(
                headers.get("message", "STOMP error frame received")
            )

        if command != "MESSAGE":
            return

        try:
            payload = json.loads(body)
        except ValueError:
            _LOGGER.debug("Skipping malformed message body: %.120s", body)
            return

        checkin = payload.get("checkin") if isinstance(payload, dict) else None
        if isinstance(checkin, dict):
            # The event kind travels in a STOMP header, not in the body.
            on_event(headers.get("event-type", ""), checkin)

    async def _heartbeat(self, websocket: aiohttp.ClientWebSocketResponse) -> None:
        """Send STOMP heartbeats so the broker keeps the subscription alive."""
        while True:
            await asyncio.sleep(WS_HEARTBEAT_MS / 1000)
            await websocket.send_str("\n")
