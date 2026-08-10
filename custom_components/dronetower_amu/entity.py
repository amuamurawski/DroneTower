"""Shared entity base for DroneTower-AMU."""

from __future__ import annotations

from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN
from .coordinator import DroneTowerCoordinator


class DroneTowerEntity(CoordinatorEntity[DroneTowerCoordinator]):
    """Base entity tying everything to one device per monitored location."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DroneTowerCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, DEFAULT_NAME),
            manufacturer="PANSA",
            model="Monitor zgłoszonych lotów",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.pansa.pl/strefy-geograficzne/",
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data is not None
