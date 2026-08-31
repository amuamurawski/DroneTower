"""End-to-end tests for setup, filtering and the live event path."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.dronetower_amu.const import (
    CONF_INCLUDE_OVERDUE,
    CONF_INCLUDE_PLANNED,
    DOMAIN,
    HA_EVENT_CLEARED,
    HA_EVENT_DETECTED,
)

from .conftest import make_checkin, make_entry


async def setup_entry(hass: HomeAssistant, config_entry) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def entity_id_for(hass: HomeAssistant, config_entry, platform: str, key: str) -> str:
    """Resolve an entity id by unique id, so tests do not depend on the UI language."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        platform, DOMAIN, f"{config_entry.entry_id}_{key}"
    )
    assert entity_id is not None, f"{platform}/{key} was never registered"
    return entity_id


def nearby_state(hass, config_entry):
    return hass.states.get(
        entity_id_for(hass, config_entry, "binary_sensor", "drone_nearby")
    )


def count_state(hass, config_entry):
    return hass.states.get(
        entity_id_for(hass, config_entry, "sensor", "drones_in_range")
    )


def nearest_state(hass, config_entry):
    return hass.states.get(entity_id_for(hass, config_entry, "sensor", "nearest_drone"))


async def test_setup_with_no_checkins(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED
    assert nearby_state(hass, config_entry).state == "off"
    assert count_state(hass, config_entry).state == "0"
    assert nearest_state(hass, config_entry).state == "unknown"


async def test_monitored_area_exposed_for_map_card(hass, config_entry, mock_client):
    """The map card reads the watched point and radius off the binary sensor."""
    await setup_entry(hass, config_entry)

    attrs = nearby_state(hass, config_entry).attributes
    assert attrs["monitored_latitude"] == 52.0
    assert attrs["monitored_longitude"] == 21.0
    assert attrs["radius_m"] == 5000


async def test_nearby_checkin_from_snapshot(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [make_checkin()]
    await setup_entry(hass, config_entry)

    state = nearby_state(hass, config_entry)
    assert state.state == "on"
    assert count_state(hass, config_entry).state == "1"

    # 52.005/21.0 sits ~556 m from home, minus the 100 m flight radius.
    nearest = int(nearest_state(hass, config_entry).state)
    assert 400 < nearest < 500

    drone = state.attributes["drones"][0]
    assert drone["id"] == "abc"
    assert drone["max_height_m"] == 120
    assert drone["status"] == "ACTIVE"


async def test_phone_number_is_never_exposed(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [make_checkin()]
    await setup_entry(hass, config_entry)

    attributes = str(nearby_state(hass, config_entry).attributes)
    assert "123456789" not in attributes
    assert "phone" not in attributes.lower()


async def test_distant_checkin_is_ignored(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [
        make_checkin(latitude=53.0, longitude=21.0)
    ]
    await setup_entry(hass, config_entry)

    assert nearby_state(hass, config_entry).state == "off"
    assert count_state(hass, config_entry).state == "0"


async def test_null_radius_is_treated_as_a_point(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [make_checkin(radius=None)]
    await setup_entry(hass, config_entry)

    assert nearby_state(hass, config_entry).state == "on"
    nearest = int(nearest_state(hass, config_entry).state)
    assert 500 < nearest < 600


async def test_overdue_excluded_by_default(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [make_checkin(status="OVERDUE")]
    await setup_entry(hass, config_entry)

    assert nearby_state(hass, config_entry).state == "off"


async def test_overdue_included_when_enabled(hass, mock_client):
    entry = make_entry(**{CONF_INCLUDE_OVERDUE: True})
    mock_client.async_get_checkins.return_value = [make_checkin(status="OVERDUE")]
    await setup_entry(hass, entry)

    assert nearby_state(hass, entry).state == "on"


async def test_planned_excluded_when_disabled(hass, mock_client):
    entry = make_entry(**{CONF_INCLUDE_PLANNED: False})
    mock_client.async_get_checkins.return_value = [make_checkin(status="CREATED")]
    await setup_entry(hass, entry)

    assert nearby_state(hass, entry).state == "off"


async def test_finished_checkin_is_never_nearby(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [make_checkin(status="FINISHED")]
    await setup_entry(hass, config_entry)

    assert nearby_state(hass, config_entry).state == "off"


async def test_live_event_adds_and_removes_drone(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)
    on_event = mock_client.captured["on_event"]

    detected: list[dict] = []
    cleared: list[dict] = []
    hass.bus.async_listen(HA_EVENT_DETECTED, lambda e: detected.append(e.data))
    hass.bus.async_listen(HA_EVENT_CLEARED, lambda e: cleared.append(e.data))

    on_event("CheckinEvent", make_checkin(checkin_id="live-1"))
    await hass.async_block_till_done()

    assert nearby_state(hass, config_entry).state == "on"
    assert count_state(hass, config_entry).state == "1"
    assert detected and detected[0]["id"] == "live-1"

    on_event("CheckinFinishedEvent", make_checkin(checkin_id="live-1"))
    await hass.async_block_till_done()

    assert nearby_state(hass, config_entry).state == "off"
    assert cleared and cleared[0]["id"] == "live-1"


async def test_terminal_status_in_event_removes_drone(hass, config_entry, mock_client):
    mock_client.async_get_checkins.return_value = [make_checkin(checkin_id="x")]
    await setup_entry(hass, config_entry)
    assert nearby_state(hass, config_entry).state == "on"

    mock_client.captured["on_event"](
        "CheckinEvent", make_checkin(checkin_id="x", status="FINISHED")
    )
    await hass.async_block_till_done()

    assert nearby_state(hass, config_entry).state == "off"


async def test_distant_live_event_does_not_trigger(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)

    mock_client.captured["on_event"](
        "CheckinEvent", make_checkin(checkin_id="far", latitude=53.0)
    )
    await hass.async_block_till_done()

    assert nearby_state(hass, config_entry).state == "off"


async def test_geo_location_marker_lifecycle(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)

    assert not hass.states.async_entity_ids("geo_location")

    mock_client.captured["on_event"]("CheckinEvent", make_checkin(checkin_id="marker1"))
    await hass.async_block_till_done()

    markers = hass.states.async_entity_ids("geo_location")
    assert len(markers) == 1
    marker = hass.states.get(markers[0])
    assert marker.attributes["latitude"] == 52.005
    assert marker.attributes["source"] == DOMAIN
    assert marker.attributes["checkin_id"] == "marker1"
    assert float(marker.state) == 0.5

    mock_client.captured["on_event"](
        "CheckinFinishedEvent", make_checkin(checkin_id="marker1")
    )
    await hass.async_block_till_done()

    assert not hass.states.async_entity_ids("geo_location")


async def test_markers_leave_no_registry_entries(hass, config_entry, mock_client):
    """Transient markers must not accumulate in the entity registry."""
    await setup_entry(hass, config_entry)

    mock_client.captured["on_event"]("CheckinEvent", make_checkin(checkin_id="m1"))
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    assert not [
        entry
        for entry in registry.entities.values()
        if entry.domain == "geo_location"
    ]


async def test_unload(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
