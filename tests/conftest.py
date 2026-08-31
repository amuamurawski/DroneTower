"""Fixtures for the DroneTower-AMU tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dronetower_amu.const import (
    CONF_INCLUDE_OVERDUE,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    DOMAIN,
)

HOME_LAT = 52.0
HOME_LON = 21.0


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom component loadable in tests."""
    yield


PHONE = "123456789"


def make_checkin(
    checkin_id: str = "abc",
    latitude: float = 52.005,
    longitude: float = 21.0,
    radius: float | None = 100.0,
    status: str = "ACTIVE",
    max_height: int = 120,
    phone: str | None = PHONE,
    consent: bool = True,
) -> dict:
    """Build a check-in shaped exactly like the real API returns."""
    return {
        "id": checkin_id,
        "status": status,
        "pilotPhoneNumber": {"countryCode": "PL", "number": phone or ""},
        "phoneNumberPublicationConsent": consent,
        "startDateTime": "2026-08-10T16:21:45.061Z",
        "endDateTime": "2099-08-10T16:51:45.061Z",
        "flightArea": {
            "maxHeight": max_height,
            "center": {"latitude": latitude, "longitude": longitude},
            "radius": radius,
        },
        "missionArea": [],
        "supervision": False,
        "messageToAnsp": "",
        "missionFinished": False,
        "fromMissionPlanner": False,
        "checkinType": "STANDARD",
        "origin": "DT",
    }


def make_entry(**option_overrides) -> MockConfigEntry:
    """Build a config entry; options cannot be reassigned after construction."""
    options = {
        "latitude": HOME_LAT,
        "longitude": HOME_LON,
        CONF_RADIUS: 5000,
        CONF_INCLUDE_PLANNED: True,
        CONF_INCLUDE_OVERDUE: False,
        **option_overrides,
    }
    return MockConfigEntry(
        domain=DOMAIN,
        title="Dom",
        data={"name": "Dom", "email": "pilot@example.com", "password": "secret"},
        options=options,
    )


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return make_entry()


@pytest.fixture
def mock_client():
    """Patch the API client, exposing the captured stream callbacks."""
    with patch(
        "custom_components.dronetower_amu.DroneTowerClient", autospec=True
    ) as client_class:
        client = client_class.return_value
        client.async_get_checkins = AsyncMock(return_value=[])
        client.captured = {}

        async def _stream(on_event, on_connected=None):
            client.captured["on_event"] = on_event
            client.captured["on_connected"] = on_connected
            if on_connected is not None:
                on_connected()
            await asyncio.Event().wait()

        client.async_run_stream = AsyncMock(side_effect=_stream)
        yield client
