"""The DroneTower-AMU integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DroneTowerClient
from .const import DOMAIN
from .coordinator import DroneTowerCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.GEO_LOCATION,
    Platform.SENSOR,
]

type DroneTowerConfigEntry = ConfigEntry[DroneTowerCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DroneTowerConfigEntry) -> bool:
    """Set up DroneTower-AMU from a config entry."""
    client = DroneTowerClient(async_get_clientsession(hass))
    coordinator = DroneTowerCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await coordinator.async_start_stream()

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DroneTowerConfigEntry) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.async_stop_stream()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: DroneTowerConfigEntry) -> None:
    """Reload when the monitored location or filters change."""
    await hass.config_entries.async_reload(entry.entry_id)
