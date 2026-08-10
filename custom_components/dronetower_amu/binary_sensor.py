"""Binary sensor telling you whether a drone flight is registered nearby."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DroneTowerConfigEntry
from .const import ATTR_DRONES, ATTR_TOTAL_ACTIVE
from .entity import DroneTowerEntity

# Keeping every nearby flight in the attributes is fine at sane radii, but the
# state attribute budget is not unlimited.
MAX_ATTRIBUTE_ENTRIES = 20


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DroneTowerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DroneNearbyBinarySensor(entry.runtime_data)])


class DroneNearbyBinarySensor(DroneTowerEntity, BinarySensorEntity):
    """On when at least one registered flight area reaches the monitored radius."""

    _attr_translation_key = "drone_nearby"
    _attr_icon = "mdi:quadcopter"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "drone_nearby")

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        return bool(data and data["nearby"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {"nearby": [], "total_active": 0}
        return {
            ATTR_DRONES: data["nearby"][:MAX_ATTRIBUTE_ENTRIES],
            ATTR_TOTAL_ACTIVE: data["total_active"],
            "stream_connected": self.coordinator.stream_connected,
        }
