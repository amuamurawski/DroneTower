"""Sensors for the DroneTower-AMU integration."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DroneTowerConfigEntry
from .coordinator import DroneTowerCoordinator
from .entity import DroneTowerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DroneTowerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            DronesInRangeSensor(coordinator),
            NearestDroneSensor(coordinator),
            TotalActiveSensor(coordinator),
            ReturningOperatorsSensor(coordinator),
            RecentFlightsSensor(coordinator),
        ]
    )


class DronesInRangeSensor(DroneTowerEntity, SensorEntity):
    """How many registered flights currently reach the monitored radius."""

    _attr_translation_key = "drones_in_range"
    _attr_icon = "mdi:quadcopter"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "drony"

    def __init__(self, coordinator: DroneTowerCoordinator) -> None:
        super().__init__(coordinator, "drones_in_range")

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data["nearby"])


class NearestDroneSensor(DroneTowerEntity, SensorEntity):
    """Distance to the edge of the closest registered flight area."""

    _attr_translation_key = "nearest_drone"
    _attr_icon = "mdi:map-marker-distance"
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: DroneTowerCoordinator) -> None:
        super().__init__(coordinator, "nearest_drone")

    @property
    def native_value(self) -> int | None:
        nearby = self.coordinator.data["nearby"]
        if not nearby:
            return None
        return nearby[0]["distance_to_area_m"]

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        nearby = self.coordinator.data["nearby"]
        if not nearby:
            return {}
        closest = nearby[0]
        return {
            "checkin_id": closest["id"],
            "status": closest["status"],
            "distance_to_center_m": closest["distance_m"],
            "max_height_m": closest["max_height_m"],
            "area_radius_m": closest["radius_m"],
            "start": closest["start"],
            "end": closest["end"],
        }


class _HistorySensor(DroneTowerEntity, SensorEntity):
    """Counter derived from the stored history.

    Deliberately carries no attributes. Putting the flight or operator list here
    would re-serialise a year of records into the recorder database on every state
    change, for no benefit over calling the actions.

    Both counters are a floor, not a truth: only about a third of check-ins publish
    a phone number, and that number is the only thing linking two flights to the
    same person.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _index: int

    @property
    def native_value(self) -> int | None:
        history = self.coordinator.history
        if history is None:
            return None
        return history.async_counters()[self._index]


class ReturningOperatorsSensor(_HistorySensor):
    """Operators that have been here more than once."""

    _attr_translation_key = "returning_operators"
    _attr_icon = "mdi:account-repeat"
    _attr_native_unit_of_measurement = "operatorzy"
    _index = 1

    def __init__(self, coordinator: DroneTowerCoordinator) -> None:
        super().__init__(coordinator, "returning_operators")


class RecentFlightsSensor(_HistorySensor):
    """Flights recorded in the last 30 days."""

    _attr_translation_key = "recent_flights"
    _attr_icon = "mdi:history"
    _attr_native_unit_of_measurement = "loty"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _index = 0

    def __init__(self, coordinator: DroneTowerCoordinator) -> None:
        super().__init__(coordinator, "recent_flights")


class TotalActiveSensor(DroneTowerEntity, SensorEntity):
    """Nationwide check-in count — useful context, disabled by default."""

    _attr_translation_key = "total_active"
    _attr_icon = "mdi:map-marker-multiple"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "zgłoszenia"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DroneTowerCoordinator) -> None:
        super().__init__(coordinator, "total_active")

    @property
    def native_value(self) -> int:
        return self.coordinator.data["total_active"]
