"""Keeps a live picture of PANSA check-ins near the monitored location."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance as geo_distance

from .api import DroneTowerClient, DroneTowerError
from .const import (
    CONF_INCLUDE_OVERDUE,
    CONF_INCLUDE_PLANNED,
    CONF_RADIUS,
    DEFAULT_INCLUDE_OVERDUE,
    DEFAULT_INCLUDE_PLANNED,
    DEFAULT_RADIUS,
    DOMAIN,
    EVENT_CHECKIN_FINISHED,
    HA_EVENT_CLEARED,
    HA_EVENT_DETECTED,
    RESYNC_INTERVAL,
    STALE_AFTER,
    STATUS_CREATED,
    STATUS_OVERDUE,
    TERMINAL_STATUSES,
    WS_RETRY_MAX,
    WS_RETRY_MIN,
)

_LOGGER = logging.getLogger(__name__)


class DroneTowerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Merges the REST snapshot with the STOMP push feed.

    The nationwide broadcast carries roughly one event per second, so pushing every
    one of them to entities would churn the recorder for no benefit. Entities are
    updated as soon as the *nearby* set changes; the nationwide counter rides along
    with those updates and with the periodic snapshot.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: DroneTowerClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=RESYNC_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self._checkins: dict[str, dict[str, Any]] = {}
        self._nearby_ids: set[str] = set()
        self._stream_task: asyncio.Task[None] | None = None
        self._retry_delay = WS_RETRY_MIN
        self.stream_connected = False

    @property
    def latitude(self) -> float:
        return self.config_entry.options["latitude"]

    @property
    def longitude(self) -> float:
        return self.config_entry.options["longitude"]

    @property
    def radius(self) -> float:
        return self.config_entry.options.get(CONF_RADIUS, DEFAULT_RADIUS)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            checkins = await self.client.async_get_checkins()
        except DroneTowerError as err:
            raise UpdateFailed(str(err)) from err

        self._checkins = {c["id"]: c for c in checkins if c.get("id")}
        return self._build()

    async def async_start_stream(self) -> None:
        """Start the background listener for live check-in events."""
        if self._stream_task is None:
            self._stream_task = self.config_entry.async_create_background_task(
                self.hass, self._stream_loop(), f"{DOMAIN}_stream"
            )

    async def async_stop_stream(self) -> None:
        if self._stream_task is not None:
            task, self._stream_task = self._stream_task, None
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            self.stream_connected = False

    async def _stream_loop(self) -> None:
        while True:
            try:
                await self.client.async_run_stream(
                    self._handle_event, self._handle_connected
                )
                _LOGGER.debug("DroneTower stream ended, reconnecting")
            except asyncio.CancelledError:
                raise
            except DroneTowerError as err:
                _LOGGER.warning(
                    "DroneTower stream lost (%s), retrying in %ss",
                    err,
                    self._retry_delay,
                )
            except Exception:  # noqa: BLE001 - a background task must never die silently
                _LOGGER.exception("Unexpected error in the DroneTower stream")

            if self.stream_connected:
                self.stream_connected = False
                self.async_update_listeners()

            await asyncio.sleep(self._retry_delay)
            # Grows until a connection actually succeeds; _handle_connected resets it.
            self._retry_delay = min(self._retry_delay * 2, WS_RETRY_MAX)

            # A dropped socket means missed events; resynchronise before listening again.
            try:
                await self.async_request_refresh()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Resync after stream loss failed, will retry")

    @callback
    def _handle_connected(self) -> None:
        self._retry_delay = WS_RETRY_MIN
        self.stream_connected = True
        self.async_update_listeners()

    @callback
    def _handle_event(self, event_type: str, checkin: dict[str, Any]) -> None:
        checkin_id = checkin.get("id")
        if not checkin_id:
            return

        finished = (
            event_type == EVENT_CHECKIN_FINISHED
            or str(checkin.get("status", "")).upper() in TERMINAL_STATUSES
        )
        if finished:
            self._checkins.pop(checkin_id, None)
        else:
            self._checkins[checkin_id] = checkin

        data = self._build()
        if self.data is None or data["nearby"] != self.data.get("nearby"):
            self.async_set_updated_data(data)

    def _build(self) -> dict[str, Any]:
        """Recompute the derived state and emit enter/leave events."""
        self._prune()

        nearby = [
            entry
            for entry in (self._evaluate(c) for c in self._checkins.values())
            if entry is not None
        ]
        nearby.sort(key=lambda item: item["distance_to_area_m"])

        self._fire_transitions(nearby)

        # stream_connected deliberately stays off the data dict: it changes without a
        # rebuild, so entities read it straight off the coordinator instead.
        return {"nearby": nearby, "total_active": len(self._checkins)}

    def _prune(self) -> None:
        """Drop check-ins that can no longer describe a flight in progress."""
        cutoff = dt_util.utcnow() - STALE_AFTER
        for checkin_id, checkin in list(self._checkins.items()):
            end = _parse_time(checkin.get("endDateTime"))
            if end is not None and end < cutoff:
                del self._checkins[checkin_id]

    def _evaluate(self, checkin: dict[str, Any]) -> dict[str, Any] | None:
        """Return a normalised entry if this check-in is close enough, else None."""
        status = str(checkin.get("status", "")).upper()
        if status in TERMINAL_STATUSES:
            return None

        options = self.config_entry.options
        if status == STATUS_OVERDUE and not options.get(
            CONF_INCLUDE_OVERDUE, DEFAULT_INCLUDE_OVERDUE
        ):
            return None
        if status == STATUS_CREATED and not options.get(
            CONF_INCLUDE_PLANNED, DEFAULT_INCLUDE_PLANNED
        ):
            return None

        area = checkin.get("flightArea") or {}
        center = area.get("center") or {}
        latitude = center.get("latitude")
        longitude = center.get("longitude")
        if latitude is None or longitude is None:
            return None

        to_center = geo_distance(self.latitude, self.longitude, latitude, longitude)
        if to_center is None:
            return None

        # radius may be null for a handful of records; treat those as a point.
        flight_radius = area.get("radius") or 0.0
        to_area = max(0.0, to_center - flight_radius)
        if to_area > self.radius:
            return None

        return {
            "id": checkin["id"],
            "status": status,
            "latitude": latitude,
            "longitude": longitude,
            "distance_m": round(to_center),
            "distance_to_area_m": round(to_area),
            "radius_m": area.get("radius"),
            "max_height_m": area.get("maxHeight"),
            "start": checkin.get("startDateTime"),
            "end": checkin.get("endDateTime"),
            "checkin_type": checkin.get("checkinType"),
            "origin": checkin.get("origin"),
            "supervision": bool(checkin.get("supervision")),
            "from_mission_planner": bool(checkin.get("fromMissionPlanner")),
            "has_mission_area": bool(checkin.get("missionArea")),
        }

    def _fire_transitions(self, nearby: list[dict[str, Any]]) -> None:
        current = {entry["id"] for entry in nearby}
        by_id = {entry["id"]: entry for entry in nearby}

        for checkin_id in current - self._nearby_ids:
            self.hass.bus.async_fire(HA_EVENT_DETECTED, dict(by_id[checkin_id]))
        for checkin_id in self._nearby_ids - current:
            self.hass.bus.async_fire(HA_EVENT_CLEARED, {"id": checkin_id})

        self._nearby_ids = current


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return dt_util.parse_datetime(value)
