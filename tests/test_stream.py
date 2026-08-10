"""Regression tests for the reconnect loop.

These reach into the coordinator's private state on purpose: the behaviour under
test is the retry timing itself, which has no public surface but decides how much
work a flaky connection generates.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from .conftest import make_checkin
from .test_init import setup_entry

MOD = "custom_components.dronetower_amu.coordinator"


class _Stop(BaseException):
    """Breaks out of the otherwise endless reconnect loop.

    Deliberately not an Exception: the loop catches those on purpose so a
    background task never dies quietly, which would swallow this too.
    """


async def _run_loop(coordinator, attempts: int, connect: bool) -> list[float]:
    """Drive the reconnect loop and record the delay used before each attempt."""
    delays: list[float] = []

    async def flapping(on_event, on_connected=None):
        delays.append(coordinator._retry_delay)
        if len(delays) >= attempts:
            raise _Stop
        if connect and on_connected is not None:
            on_connected()
        # Returning immediately models a socket that drops as soon as it opens.

    coordinator.client.async_run_stream = AsyncMock(side_effect=flapping)
    coordinator._retry_delay = 0.001
    # The task started during setup already reported a connection; clear it so the
    # loop under test starts from a known state.
    coordinator.stream_connected = False

    with pytest.raises(_Stop):
        await coordinator._stream_loop()

    return delays


async def test_flapping_connection_backs_off(hass, config_entry, mock_client):
    """A socket that connects then drops must not keep retrying at the minimum.

    Resetting the backoff on CONNECT alone turned a flaky link into a reconnect
    plus full REST resync every few seconds, indefinitely.
    """
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data

    delays = await _run_loop(coordinator, attempts=4, connect=True)

    assert delays == [0.001, 0.002, 0.004, 0.008]


async def test_stable_session_resets_backoff(hass, config_entry, mock_client):
    """A connection that held up long enough starts the next retry from scratch."""
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data

    with patch(f"{MOD}.WS_STABLE_AFTER", 0), patch(f"{MOD}.WS_RETRY_MIN", 0.001):
        delays = await _run_loop(coordinator, attempts=4, connect=True)

    assert delays == [0.001, 0.001, 0.001, 0.001]


async def test_no_resync_when_connection_never_established(
    hass, config_entry, mock_client
):
    """Failing to connect says nothing new about the check-in list."""
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data
    mock_client.async_get_checkins.reset_mock()

    with patch.object(coordinator, "async_request_refresh") as refresh:
        await _run_loop(coordinator, attempts=3, connect=False)

    refresh.assert_not_called()


async def test_resync_requested_after_losing_a_live_stream(
    hass, config_entry, mock_client
):
    """Losing a stream that was working means events were missed."""
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data

    with patch.object(coordinator, "async_request_refresh") as refresh:
        await _run_loop(coordinator, attempts=3, connect=True)

    assert refresh.call_count >= 1


async def test_event_only_touches_the_named_checkin(hass, config_entry, mock_client):
    """The per-event path must not re-derive every check-in in the country."""
    mock_client.async_get_checkins.return_value = [
        make_checkin(checkin_id=f"c{i}", latitude=53.0 + i / 1000) for i in range(50)
    ]
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data

    with patch(f"{MOD}.geo_distance", return_value=100.0) as distance:
        coordinator._handle_event("CheckinEvent", make_checkin(checkin_id="new"))

    assert distance.call_count == 1, "jedno zdarzenie = jeden pomiar odległości"
