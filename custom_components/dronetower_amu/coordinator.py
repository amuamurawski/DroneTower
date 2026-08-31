"""Keeps a live picture of PANSA check-ins near the monitored location."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance as geo_distance

from .api import DroneTowerAuthError, DroneTowerClient, DroneTowerError
from .history import FlightHistory
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
    HA_EVENT_KNOWN_OPERATOR,
    RESYNC_INTERVAL,
    STALE_AFTER,
    STATUS_CREATED,
    STATUS_OVERDUE,
    TERMINAL_STATUSES,
    WS_RETRY_MAX,
    WS_RETRY_MIN,
    WS_STABLE_AFTER,
)

_LOGGER = logging.getLogger(__name__)


class DroneTowerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Merges the REST snapshot with the STOMP push feed.

    The nationwide broadcast carries roughly one event per second for the whole
    country, so anything done per event is done 86 000 times a day. Each check-in
    is therefore parsed and measured once, when it arrives, and an event only
    touches the one record it names. Entities are updated when the *nearby* set
    changes; the nationwide counter rides along with those updates and with the
    periodic snapshot.
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
        # Derived once per check-in: its normalised payload (or None when out of
        # range) and its parsed end time. Keeping these off the per-event path is
        # what makes an event O(1) instead of O(all check-ins in Poland).
        self._derived: dict[str, dict[str, Any] | None] = {}
        self._expiry: dict[str, datetime | None] = {}
        self._nearby_ids: set[str] = set()
        self._stream_task: asyncio.Task[None] | None = None
        self._retry_delay = WS_RETRY_MIN
        self.stream_connected = False
        # Injected after construction: persistence is not the coordinator's job, it
        # only knows who to hand an arrival to.
        self.history: FlightHistory | None = None

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
        except DroneTowerAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DroneTowerError as err:
            raise UpdateFailed(str(err)) from err

        self._checkins.clear()
        self._derived.clear()
        self._expiry.clear()
        for checkin in checkins:
            if checkin.get("id"):
                self._store(checkin)

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
            started = self.hass.loop.time()
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

            was_connected = self.stream_connected
            if was_connected:
                self.stream_connected = False
                self.async_update_listeners()

            # Only a session that actually held up clears the backoff. Resetting on
            # CONNECT alone would let a socket that drops immediately reconnect and
            # resynchronise every few seconds, forever.
            stable = self.hass.loop.time() - started >= WS_STABLE_AFTER
            if stable:
                self._retry_delay = WS_RETRY_MIN

            await asyncio.sleep(self._retry_delay)

            if not stable:
                self._retry_delay = min(self._retry_delay * 2, WS_RETRY_MAX)

            # A dropped socket means missed events, so resynchronise — but only if
            # we had a working stream to lose. Retrying a connection that never
            # succeeded says nothing new about the check-in list.
            if was_connected:
                try:
                    await self.async_request_refresh()
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Resync after stream loss failed, will retry")

    @callback
    def _handle_connected(self) -> None:
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
            self._forget(checkin_id)
        else:
            self._store(checkin)

        data = self._build()
        if self.data is None or data["nearby"] != self.data.get("nearby"):
            self.async_set_updated_data(data)

    def _store(self, checkin: dict[str, Any]) -> None:
        """Record a check-in, doing the parsing and geodesy exactly once."""
        checkin_id = checkin["id"]
        self._checkins[checkin_id] = checkin
        self._expiry[checkin_id] = _parse_time(checkin.get("endDateTime"))
        self._derived[checkin_id] = self._evaluate(checkin)

    def _forget(self, checkin_id: str) -> None:
        self._checkins.pop(checkin_id, None)
        self._derived.pop(checkin_id, None)
        self._expiry.pop(checkin_id, None)

    def _build(self) -> dict[str, Any]:
        """Assemble the derived state from cached per-check-in results."""
        self._prune()

        nearby = [entry for entry in self._derived.values() if entry is not None]
        nearby.sort(key=lambda item: item["distance_to_area_m"])

        self._fire_transitions(nearby)

        # stream_connected deliberately stays off the data dict: it changes without a
        # rebuild, so entities read it straight off the coordinator instead.
        return {"nearby": nearby, "total_active": len(self._checkins)}

    def _prune(self) -> None:
        """Drop check-ins that can no longer describe a flight in progress.

        Uses the end time parsed at store time, so this is a datetime comparison
        per check-in rather than a re-parse.
        """
        cutoff = dt_util.utcnow() - STALE_AFTER
        expired = [
            checkin_id
            for checkin_id, end in self._expiry.items()
            if end is not None and end < cutoff
        ]
        for checkin_id in expired:
            self._forget(checkin_id)

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
        if current == self._nearby_ids:
            return

        by_id = {entry["id"]: entry for entry in nearby}
        for checkin_id in current - self._nearby_ids:
            derived = by_id[checkin_id]
            self.hass.bus.async_fire(HA_EVENT_DETECTED, dict(derived))
            self._record_arrival(checkin_id, derived)
        for checkin_id in self._nearby_ids - current:
            self.hass.bus.async_fire(HA_EVENT_CLEARED, {"id": checkin_id})

        self._nearby_ids = current

    def _record_arrival(self, checkin_id: str, derived: dict[str, Any]) -> None:
        """Persist the arrival and announce an operator that has been here before.

        Arrival, not departure, is the recording point: a check-in that simply
        vanishes from a REST snapshot never passes through `_forget`, so departure
        would silently lose flights.
        """
        if self.history is None:
            return

        raw = self._checkins.get(checkin_id)
        if raw is None:
            return

        announce = self.history.async_record(raw, derived)
        if announce is None:
            return

        # Carries the pseudonymous key, never the phone number: events reach the
        # bus, the logs and anything listening. An automation that needs to call
        # someone fetches the number with the get_operator action.
        self.hass.bus.async_fire(
            HA_EVENT_KNOWN_OPERATOR,
            {
                "id": checkin_id,
                "operator": announce["operator"],
                "previous_flights": announce["previous_flights"],
                "previously_seen": announce["last_seen"],
                "previously_closest_m": announce["closest_m"],
                "distance_to_area_m": derived["distance_to_area_m"],
                "max_height_m": derived["max_height_m"],
            },
        )


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return dt_util.parse_datetime(value)
