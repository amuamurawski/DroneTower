"""REST and STOMP-over-WebSocket client for the PANSA DroneTower BFF."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from typing import Any

import aiohttp

from .const import (
    AUTH_ENDPOINT,
    CHECKINS_ENDPOINT,
    CONTENT_TYPE,
    STOMP_PROTOCOLS,
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
        # Serialises logins so a burst of 401s triggers one refresh, not a stampede.
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
        """Exchange email + password for a bearer token.

        Raises DroneTowerAuthError when the backend refuses the credentials (or none
        are configured), so the caller can start a reauth flow rather than retry.
        """
        if not self.has_credentials:
            raise DroneTowerAuthError("No DroneTower credentials configured")

        async with self._login_lock:
            try:
                async with self._session.post(
                    AUTH_ENDPOINT,
                    json={"email": self._email, "password": self._password},
                    headers={"content-type": CONTENT_TYPE, "accept": CONTENT_TYPE},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status in (401, 403):
                        raise DroneTowerAuthError(
                            "DroneTower rejected the email or password"
                        )
                    if response.status == 429:
                        raise DroneTowerError("Rate limited by the DroneTower backend")
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
            except TimeoutError as err:
                raise DroneTowerError("Timeout logging in to DroneTower") from err
            except aiohttp.ClientError as err:
                raise DroneTowerError(f"DroneTower login failed: {err}") from err

            token = payload.get("accessToken") if isinstance(payload, dict) else None
            if not token:
                raise DroneTowerError("DroneTower login returned no access token")
            self._token = token

    async def async_get_checkins(self) -> list[dict[str, Any]]:
        """Fetch the nationwide snapshot of active check-ins.

        Logs in on first use, and re-logs in once if the token has expired.
        """
        if self._token is None:
            await self.async_login()

        # Two passes at most: the second only after a fresh login on a 401.
        for attempt in range(2):
            try:
                async with self._session.get(
                    CHECKINS_ENDPOINT,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status in (401, 403):
                        if attempt == 0:
                            self._token = None
                            await self.async_login()
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
