"""Map markers for registered flights near the monitored location."""

from __future__ import annotations

from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DroneTowerConfigEntry
from .const import DOMAIN
from .coordinator import DroneTowerCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DroneTowerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    manager = DroneMarkerManager(entry.runtime_data, async_add_entities)
    entry.async_on_unload(entry.runtime_data.async_add_listener(manager.sync))
    manager.sync()


class DroneMarkerManager:
    """Creates and removes a marker per nearby flight as the feed changes."""

    def __init__(
        self,
        coordinator: DroneTowerCoordinator,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self._coordinator = coordinator
        self._async_add_entities = async_add_entities
        self._markers: dict[str, DroneMarker] = {}

    @callback
    def sync(self) -> None:
        data = self._coordinator.data
        if data is None:
            return

        current = {entry["id"]: entry for entry in data["nearby"]}

        new_markers = [
            DroneMarker(self._coordinator, checkin_id, entry)
            for checkin_id, entry in current.items()
            if checkin_id not in self._markers
        ]
        for marker in new_markers:
            self._markers[marker.checkin_id] = marker
        if new_markers:
            self._async_add_entities(new_markers)

        for checkin_id in set(self._markers) - set(current):
            self._markers.pop(checkin_id).async_schedule_removal()


class DroneMarker(CoordinatorEntity[DroneTowerCoordinator], GeolocationEvent):
    """A single registered flight shown on the Home Assistant map.

    Markers are transient, so like the geo_location platforms in core they carry no
    unique_id — otherwise every drone that ever passed would leave a registry entry
    behind.
    """

    _attr_source = DOMAIN
    _attr_icon = "mdi:quadcopter"
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DroneTowerCoordinator,
        checkin_id: str,
        initial: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self.checkin_id = checkin_id
        self._data = initial
        self._attr_name = f"Dron {checkin_id[:8]}"

    @property
    def _entry(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        for entry in data["nearby"]:
            if entry["id"] == self.checkin_id:
                return entry
        return None

    @callback
    def _handle_coordinator_update(self) -> None:
        if (entry := self._entry) is not None:
            self._data = entry
        super()._handle_coordinator_update()

    @callback
    def async_schedule_removal(self) -> None:
        if self.hass is not None:
            self.hass.async_create_task(self.async_remove(force_remove=True))

    @property
    def available(self) -> bool:
        return self._entry is not None

    @property
    def latitude(self) -> float:
        return self._data["latitude"]

    @property
    def longitude(self) -> float:
        return self._data["longitude"]

    @property
    def distance(self) -> float:
        return round(self._data["distance_to_area_m"] / 1000, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "checkin_id": self._data["id"],
            "status": self._data["status"],
            "distance_to_center_m": self._data["distance_m"],
            "area_radius_m": self._data["radius_m"],
            "max_height_m": self._data["max_height_m"],
            "start": self._data["start"],
            "end": self._data["end"],
            "checkin_type": self._data["checkin_type"],
            "origin": self._data["origin"],
            "from_mission_planner": self._data["from_mission_planner"],
        }
