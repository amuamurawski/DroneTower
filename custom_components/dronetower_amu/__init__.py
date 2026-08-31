"""The DroneTower-AMU integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DroneTowerClient
from .const import (
    DOMAIN,
    SERVICE_GET_HISTORY,
    SERVICE_GET_OPERATOR,
    SERVICE_GET_OPERATORS,
    SERVICE_PURGE_HISTORY,
)
from .coordinator import DroneTowerCoordinator
from .history import FlightHistory

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.GEO_LOCATION,
    Platform.SENSOR,
]

type DroneTowerConfigEntry = ConfigEntry[DroneTowerCoordinator]

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

_HISTORY_SCHEMA = vol.Schema(
    {
        vol.Optional("days"): cv.positive_int,
        vol.Optional("limit"): cv.positive_int,
        vol.Optional("operator"): cv.string,
        vol.Optional("only_returning", default=False): cv.boolean,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

_OPERATOR_SCHEMA = vol.Schema(
    {
        vol.Required("operator"): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

_OPERATORS_SCHEMA = vol.Schema(
    {
        vol.Optional("days"): cv.positive_int,
        vol.Optional("min_flights", default=1): cv.positive_int,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

_PURGE_SCHEMA = vol.Schema(
    {
        vol.Optional("older_than_days"): cv.positive_int,
        vol.Optional("operator"): cv.string,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: DroneTowerConfigEntry) -> bool:
    """Set up DroneTower-AMU from a config entry."""
    history = FlightHistory(hass, entry)
    await history.async_load()

    client = DroneTowerClient(
        async_get_clientsession(hass),
        entry.data.get(CONF_EMAIL),
        entry.data.get(CONF_PASSWORD),
    )
    coordinator = DroneTowerCoordinator(hass, entry, client)
    coordinator.history = history

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start_stream()

    _async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DroneTowerConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = entry.runtime_data
    await coordinator.async_stop_stream()
    if coordinator.history is not None:
        await coordinator.history.async_flush()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: DroneTowerConfigEntry) -> None:
    """Reload when the monitored location or filters change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _selected_entries(
    hass: HomeAssistant, call: ServiceCall
) -> list[DroneTowerConfigEntry]:
    """Loaded entries the call applies to — all of them unless one is named."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    wanted = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if wanted:
        entries = [entry for entry in entries if entry.entry_id == wanted]
    return entries


def _tagged(entry: DroneTowerConfigEntry, rows: list[dict[str, Any]]) -> list[dict]:
    """Label rows with their location, since several may be monitored."""
    for row in rows:
        row["location"] = entry.title
        row[ATTR_CONFIG_ENTRY_ID] = entry.entry_id
    return rows


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the domain-wide actions once, on the first entry set up."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_HISTORY):
        return

    async def get_history(call: ServiceCall) -> ServiceResponse:
        flights: list[dict[str, Any]] = []
        for entry in _selected_entries(hass, call):
            history = entry.runtime_data.history
            if history is None:
                continue
            flights.extend(
                _tagged(
                    entry,
                    history.async_flights(
                        days=call.data.get("days"),
                        limit=call.data.get("limit"),
                        operator=call.data.get("operator"),
                        only_returning=call.data.get("only_returning", False),
                    ),
                )
            )
        flights.sort(key=lambda row: row["last_seen"], reverse=True)
        return {"flights": flights, "count": len(flights)}

    async def get_operators(call: ServiceCall) -> ServiceResponse:
        operators: list[dict[str, Any]] = []
        for entry in _selected_entries(hass, call):
            history = entry.runtime_data.history
            if history is None:
                continue
            operators.extend(
                _tagged(
                    entry,
                    history.async_operators(
                        days=call.data.get("days"),
                        min_flights=call.data.get("min_flights", 1),
                    ),
                )
            )
        operators.sort(key=lambda row: (-row["flights"], row["last_seen"]))
        return {"operators": operators, "count": len(operators)}

    async def get_operator(call: ServiceCall) -> ServiceResponse:
        """The one action that reveals a phone number.

        Deliberately separate from get_operators so that browsing the history can
        never put a number into a response variable, and so an audit of who can see
        numbers is a single grep.
        """
        wanted = call.data["operator"]
        for entry in _selected_entries(hass, call):
            history = entry.runtime_data.history
            if history is None:
                continue
            if (found := history.async_operator(wanted)) is not None:
                found["location"] = entry.title
                found[ATTR_CONFIG_ENTRY_ID] = entry.entry_id
                return found
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_operator",
            translation_placeholders={"operator": wanted},
        )

    async def purge_history(call: ServiceCall) -> ServiceResponse:
        removed = 0
        for entry in _selected_entries(hass, call):
            history = entry.runtime_data.history
            if history is not None:
                removed += await history.async_purge(
                    older_than_days=call.data.get("older_than_days"),
                    operator=call.data.get("operator"),
                )
        return {"removed": removed}

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_HISTORY,
        get_history,
        schema=_HISTORY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_OPERATORS,
        get_operators,
        schema=_OPERATORS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_OPERATOR,
        get_operator,
        schema=_OPERATOR_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PURGE_HISTORY,
        purge_history,
        schema=_PURGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
