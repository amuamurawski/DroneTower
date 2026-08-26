"""Tests for the persistent flight history and its privacy guarantees."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.dronetower_amu.const import (
    CONF_HISTORY_DAYS,
    CONF_STORE_PHONE,
    DOMAIN,
    HA_EVENT_CLEARED,
    HA_EVENT_DETECTED,
    HA_EVENT_KNOWN_OPERATOR,
    SERVICE_GET_HISTORY,
    SERVICE_GET_OPERATOR,
    SERVICE_GET_OPERATORS,
    SERVICE_PURGE_HISTORY,
)

from .conftest import PHONE, make_checkin, make_entry
from .test_init import setup_entry


def arrive(hass: HomeAssistant, mock_client, **kwargs) -> None:
    """Push a check-in through the live path so it enters range."""
    mock_client.captured["on_event"]("CheckinEvent", make_checkin(**kwargs))


def last_flight_entity(hass: HomeAssistant, entry) -> str:
    from homeassistant.helpers import entity_registry as er

    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_last_flight"
    )


def depart(hass: HomeAssistant, mock_client, checkin_id: str) -> None:
    mock_client.captured["on_event"](
        "CheckinFinishedEvent", make_checkin(checkin_id=checkin_id)
    )


async def test_flight_recorded_on_arrival(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    flights = history.async_flights()
    assert len(flights) == 1
    flight = flights[0]
    assert flight["id"] == "f1"
    assert flight["passes"] == 1
    assert flight["first_seen"] == flight["last_seen"]
    assert 400 < flight["closest_m"] < 500


async def test_flight_record_carries_no_phone(hass, config_entry, mock_client):
    """Flight records are free of personal data by construction."""
    entry = make_entry(**{CONF_STORE_PHONE: True})
    await setup_entry(hass, entry)
    history = entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    assert PHONE not in str(history.async_flights())


async def test_reentry_within_grace_is_not_a_new_pass(hass, config_entry, mock_client):
    """Boundary jitter and post-restart re-arrivals must not inflate the count."""
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    depart(hass, mock_client, "f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    flights = history.async_flights()
    assert len(flights) == 1, "jeden lot to jeden wiersz"
    assert flights[0]["passes"] == 1


async def test_reentry_after_grace_counts_as_another_pass(
    hass, config_entry, mock_client
):
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    # Age the record past the grace window instead of waiting it out.
    stale = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
    history._flights["f1"]["last_seen"] = stale

    depart(hass, mock_client, "f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    assert history.async_flights()[0]["passes"] == 2


async def test_closest_approach_only_ever_decreases(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1", latitude=52.02)
    await hass.async_block_till_done()
    far = history.async_flights()[0]["closest_m"]

    depart(hass, mock_client, "f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f1", latitude=52.001)
    await hass.async_block_till_done()
    closer = history.async_flights()[0]["closest_m"]

    assert closer < far


@pytest.mark.parametrize(
    ("phone", "consent"),
    [(PHONE, False), (None, True), ("12", True)],
    ids=["no-consent", "no-number", "junk-number"],
)
async def test_unidentifiable_pilot_gets_no_operator(
    hass, config_entry, mock_client, phone, consent
):
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1", phone=phone, consent=consent)
    await hass.async_block_till_done()

    assert history.async_flights()[0]["operator"] is None
    assert history.async_operators() == []


async def test_two_flights_same_phone_are_one_operator(
    hass, config_entry, mock_client
):
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()

    operators = history.async_operators()
    assert len(operators) == 1
    assert operators[0]["flights"] == 2
    assert history.async_counters()[1] == 1, "jeden powracający operator"


async def test_operator_key_is_salted_and_hides_the_number(
    hass, config_entry, mock_client
):
    await setup_entry(hass, config_entry)
    history = config_entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    key = history.async_flights()[0]["operator"]
    assert PHONE not in key
    unsalted = hashlib.blake2b(f"PL:{PHONE}".encode(), digest_size=8).hexdigest()
    assert key != unsalted, "bez soli 10^9 numerów łamie się w sekundę"


async def test_history_and_operator_key_survive_a_reload(
    hass, config_entry, mock_client
):
    """Changing an option reloads the entry; history must outlive that."""
    await setup_entry(hass, config_entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    before = config_entry.runtime_data.history.async_flights()[0]["operator"]

    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    flights = config_entry.runtime_data.history.async_flights()
    assert len(flights) == 1
    assert flights[0]["operator"] == before


async def test_retention_drops_old_records(hass, mock_client):
    entry = make_entry(**{CONF_HISTORY_DAYS: 30})
    await setup_entry(hass, entry)
    history = entry.runtime_data.history

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    history._flights["f1"]["last_seen"] = (
        dt_util.utcnow() - timedelta(days=90)
    ).isoformat()
    await history.async_purge(older_than_days=30)

    assert history.async_flights() == []
    assert history.async_operators() == [], "operator bez lotów znika razem z nimi"


async def test_phone_stored_only_when_enabled(hass, mock_client):
    off = make_entry()
    await setup_entry(hass, off)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    key = off.runtime_data.history.async_flights()[0]["operator"]
    assert off.runtime_data.history.async_operator(key)["phone"] is None

    on = make_entry(**{CONF_STORE_PHONE: True})
    await setup_entry(hass, on)
    arrive(hass, mock_client, checkin_id="f2")
    await hass.async_block_till_done()
    key = on.runtime_data.history.async_flights()[0]["operator"]
    assert PHONE in on.runtime_data.history.async_operator(key)["phone"]


async def test_disabling_the_option_scrubs_stored_numbers(hass, mock_client):
    entry = make_entry(**{CONF_STORE_PHONE: True})
    await setup_entry(hass, entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    key = entry.runtime_data.history.async_flights()[0]["operator"]
    assert entry.runtime_data.history.async_operator(key)["number"] is not None

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_STORE_PHONE: False}
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.history.async_operator(key)["number"] is None


async def test_known_operator_event_fires_on_the_second_flight(
    hass, config_entry, mock_client
):
    await setup_entry(hass, config_entry)
    seen: list[dict] = []
    hass.bus.async_listen(HA_EVENT_KNOWN_OPERATOR, lambda e: seen.append(e.data))

    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    assert seen == [], "pierwszy lot to jeszcze nie powrót"

    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()

    assert len(seen) == 1
    assert seen[0]["previous_flights"] == 1
    assert seen[0]["id"] == "f2"
    assert PHONE not in str(seen[0])
    assert "phone" not in str(seen[0]).lower()


async def test_known_operator_does_not_refire_for_the_same_flight(
    hass, config_entry, mock_client
):
    await setup_entry(hass, config_entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()

    seen: list[dict] = []
    hass.bus.async_listen(HA_EVENT_KNOWN_OPERATOR, lambda e: seen.append(e.data))

    depart(hass, mock_client, "f2")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()

    assert seen == []


async def test_phone_never_reaches_the_integrations_own_events(hass, mock_client):
    """Absolute, regardless of settings: our events carry the pseudonym, not the number.

    State-change events do carry attributes, so this checks the three events the
    integration fires itself — the ones automations subscribe to.
    """
    entry = make_entry(**{CONF_STORE_PHONE: True})
    payloads: list[str] = []
    for event in (HA_EVENT_DETECTED, HA_EVENT_CLEARED, HA_EVENT_KNOWN_OPERATOR):
        hass.bus.async_listen(event, lambda e: payloads.append(str(e.data)))

    await setup_entry(hass, entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()
    depart(hass, mock_client, "f1")
    await hass.async_block_till_done()

    assert payloads, "zdarzenia w ogóle poleciały"
    assert PHONE not in "".join(payloads)


async def test_phone_absent_from_every_state_when_storage_is_off(
    hass, config_entry, mock_client
):
    """The default install must never surface a number anywhere."""
    await setup_entry(hass, config_entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    states = str([state.as_dict() for state in hass.states.async_all()])
    assert PHONE not in states
    assert "phone" not in states.lower()


async def test_phone_appears_in_last_flight_attributes_when_storage_is_on(
    hass, mock_client
):
    """Documents the deliberate trade-off: attributes reach the recorder database."""
    entry = make_entry(**{CONF_STORE_PHONE: True})
    await setup_entry(hass, entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    state = hass.states.get(last_flight_entity(hass, entry))
    assert PHONE in state.attributes["phone"]
    assert state.attributes["checkin_id"] == "f1"
    assert state.attributes["returning"] is False
    assert state.attributes["operator"] is not None

    # Only this one entity carries it; the others stay clean.
    others = [
        s.as_dict()
        for s in hass.states.async_all()
        if s.entity_id != last_flight_entity(hass, entry)
    ]
    assert PHONE not in str(others)


async def test_last_flight_tracks_the_newest_arrival(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()

    state = hass.states.get(last_flight_entity(hass, config_entry))
    assert state.attributes["checkin_id"] == "f2"
    assert state.attributes["returning"] is True, "ten sam numer, drugi lot"
    assert state.attributes["operator_flights"] == 2


async def test_services_expose_the_number_only_through_get_operator(
    hass, mock_client
):
    entry = make_entry(**{CONF_STORE_PHONE: True})
    await setup_entry(hass, entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()

    flights = await hass.services.async_call(
        DOMAIN, SERVICE_GET_HISTORY, {}, blocking=True, return_response=True
    )
    assert flights["count"] == 1
    assert flights["flights"][0]["location"] == "Dom"
    assert PHONE not in str(flights)

    operators = await hass.services.async_call(
        DOMAIN, SERVICE_GET_OPERATORS, {}, blocking=True, return_response=True
    )
    assert operators["count"] == 1
    assert operators["operators"][0]["has_phone"] is True
    assert PHONE not in str(operators), "przeglądanie historii nie ujawnia numeru"

    key = operators["operators"][0]["operator"]
    operator = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_OPERATOR,
        {"operator": key},
        blocking=True,
        return_response=True,
    )
    assert PHONE in operator["phone"]


async def test_get_operator_rejects_an_unknown_key(hass, config_entry, mock_client):
    await setup_entry(hass, config_entry)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_OPERATOR,
            {"operator": "nie-ma-takiego"},
            blocking=True,
            return_response=True,
        )


async def test_purge_removes_a_single_operator(hass, mock_client):
    entry = make_entry(**{CONF_STORE_PHONE: True})
    await setup_entry(hass, entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    key = entry.runtime_data.history.async_flights()[0]["operator"]

    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_PURGE_HISTORY,
        {"operator": key},
        blocking=True,
        return_response=True,
    )

    assert result["removed"] == 1
    assert entry.runtime_data.history.async_flights() == []
    assert entry.runtime_data.history.async_operator(key) is None


async def test_history_sensors_report_counts_without_attributes(
    hass, config_entry, mock_client
):
    from homeassistant.helpers import entity_registry as er

    await setup_entry(hass, config_entry)
    arrive(hass, mock_client, checkin_id="f1")
    await hass.async_block_till_done()
    arrive(hass, mock_client, checkin_id="f2", latitude=52.006)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{config_entry.entry_id}_returning_operators"
    )
    state = hass.states.get(entity_id)

    assert state.state == "1"
    # Only the framework's own attributes; no flight or operator lists.
    assert not set(state.attributes) - {
        "friendly_name",
        "icon",
        "state_class",
        "unit_of_measurement",
        "device_class",
    }
