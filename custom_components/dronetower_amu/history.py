"""Local, persistent history of flights that came near the monitored point.

**The pilot's phone number lives in this module and nowhere else.** Flight records
are free of personal data by construction: they carry only an opaque `operator`
token. The number sits once per operator in `_operators` and leaves this module
through exactly two methods: `async_operator` and `async_last_flight`, and only
while phone storage is switched on. Everything else — the flight list, the operator
summaries, the counters — stays free of it, which is what keeps the events, the
diagnostics and the browse-my-history action safe without any redaction logic.

The store lives outside the coordinator because the coordinator is rebuilt on every
options change and wiped on every REST resync, while the history must outlive both.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HISTORY_DAYS,
    CONF_STORE_PHONE,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_STORE_PHONE,
    HISTORY_MAX_FLIGHTS,
    HISTORY_MAX_OPERATORS,
    HISTORY_RECENT_DAYS,
    HISTORY_SAVE_DELAY,
    RE_ENTRY_GRACE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

MIN_PHONE_DIGITS = 6


def _phone_parts(raw: dict[str, Any]) -> tuple[str, str] | None:
    """Return `(country, digits)` for a pilot who published their number.

    This is the only field in the API that links two flights to the same person:
    `id` is per flight and no operator or pilot number is returned. Roughly a third
    of check-ins carry it.
    """
    if not raw.get("phoneNumberPublicationConsent"):
        return None
    phone = raw.get("pilotPhoneNumber") or {}
    digits = "".join(ch for ch in str(phone.get("number") or "") if ch.isdigit())
    if len(digits) < MIN_PHONE_DIGITS:
        return None
    country = str(phone.get("countryCode") or "").strip().upper()
    return country, digits


class FlightHistory:
    """Flights recorded once each, plus an operator index keyed by a salted hash."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        self._store = Store[dict[str, Any]](
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}.{entry.entry_id}",
            private=True,
        )
        self._flights: dict[str, dict[str, Any]] = {}
        self._operators: dict[str, dict[str, Any]] = {}
        self._salt = b""

    @property
    def retention_days(self) -> int:
        return int(self._entry.options.get(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS))

    @property
    def stores_phone(self) -> bool:
        return bool(self._entry.options.get(CONF_STORE_PHONE, DEFAULT_STORE_PHONE))

    async def async_load(self) -> None:
        """Read the store, mint a salt on first run, and apply current settings."""
        data = await self._store.async_load() or {}

        salt_hex = data.get("salt")
        self._salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(32)

        self._flights = {
            flight["id"]: flight
            for flight in data.get("flights") or []
            if isinstance(flight, dict) and flight.get("id")
        }
        self._operators = {
            key: value
            for key, value in (data.get("operators") or {}).items()
            if isinstance(value, dict)
        }

        # Turning the option off has to mean something, so drop numbers collected
        # while it was on rather than leaving them sitting on disk.
        scrubbed = False
        if not self.stores_phone:
            for operator in self._operators.values():
                if operator.get("number") is not None:
                    operator["number"] = None
                    operator["country_code"] = None
                    scrubbed = True

        if self._prune() or scrubbed or not salt_hex:
            await self._store.async_save(self._as_dict())

    async def async_flush(self) -> None:
        """Write immediately, cancelling any pending delayed save.

        Must run before the entry unloads. A reload builds a fresh `Store`, which
        knows nothing about the previous instance's queued write, so anything still
        waiting out the delay would be read back as stale — and an options change
        reloads the entry.
        """
        await self._store.async_save(self._as_dict())

    def _as_dict(self) -> dict[str, Any]:
        return {
            "salt": self._salt.hex(),
            "flights": list(self._flights.values()),
            "operators": self._operators,
        }

    def _schedule_save(self) -> None:
        self._store.async_delay_save(self._as_dict, HISTORY_SAVE_DELAY)

    def _operator_key(self, country: str, digits: str) -> str:
        """Keyed hash, not a bare digest.

        An unsalted hash of a nine-digit number has a keyspace of 10^9 and falls in
        under a second, so it would protect nothing. The salt is what lets flight
        records, events and logs carry this token safely.
        """
        return hashlib.blake2b(
            f"{country}:{digits}".encode(), key=self._salt, digest_size=8
        ).hexdigest()

    @callback
    def async_record(
        self, raw: dict[str, Any], derived: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Record a flight that entered range. Always persists.

        Returns `{"operator", "previous_flights", "last_seen", "closest_m"}` when
        this is a *new* flight by an identifiable operator, otherwise None. A repeat
        sighting is not a new flight and must not re-announce anyone; a pilot who
        did not publish a number cannot be correlated at all.
        """
        now = dt_util.utcnow()
        stamp = now.isoformat()
        flight_id = derived["id"]
        distance = derived["distance_to_area_m"]

        existing = self._flights.get(flight_id)
        if existing is not None:
            # A flight drifting across the radius edge, or every airborne flight
            # right after a restart, must not count as a fresh visit.
            gap = now - dt_util.parse_datetime(existing["last_seen"])
            if gap > RE_ENTRY_GRACE:
                existing["passes"] = existing.get("passes", 1) + 1
            existing["last_seen"] = stamp
            existing["closest_m"] = min(existing["closest_m"], distance)
            existing["status"] = derived["status"]
            self._touch_operator(existing.get("operator"), stamp, distance)
            self._schedule_save()
            return None

        parts = _phone_parts(raw)
        operator_key = self._operator_key(*parts) if parts else None

        previous: dict[str, Any] | None = None
        if operator_key is not None:
            previous = self._operators.get(operator_key)

        self._flights[flight_id] = {
            "id": flight_id,
            "operator": operator_key,
            "first_seen": stamp,
            "last_seen": stamp,
            "passes": 1,
            "closest_m": distance,
            "closest_center_m": derived["distance_m"],
            "latitude": derived["latitude"],
            "longitude": derived["longitude"],
            "radius_m": derived["radius_m"],
            "max_height_m": derived["max_height_m"],
            "status": derived["status"],
            "checkin_type": derived["checkin_type"],
            "origin": derived["origin"],
            "start": derived["start"],
            "end": derived["end"],
        }

        announce: dict[str, Any] | None = None
        if operator_key is not None and parts is not None:
            if previous is None:
                self._operators[operator_key] = {
                    "operator": operator_key,
                    "first_seen": stamp,
                    "last_seen": stamp,
                    "flights": 1,
                    "closest_m": distance,
                    "country_code": parts[0] if self.stores_phone else None,
                    "number": parts[1] if self.stores_phone else None,
                }
            else:
                announce = {
                    "operator": operator_key,
                    "previous_flights": previous["flights"],
                    "last_seen": previous["last_seen"],
                    "closest_m": previous["closest_m"],
                }
                previous["flights"] += 1
                previous["last_seen"] = stamp
                previous["closest_m"] = min(previous["closest_m"], distance)
                # Backfill if the option was switched on after this operator's
                # first flight.
                if self.stores_phone and previous.get("number") is None:
                    previous["country_code"], previous["number"] = parts

        self._prune()
        self._schedule_save()
        return announce

    def _touch_operator(
        self, operator_key: str | None, stamp: str, distance: int
    ) -> None:
        operator = self._operators.get(operator_key or "")
        if operator is None:
            return
        operator["last_seen"] = max(operator["last_seen"], stamp)
        operator["closest_m"] = min(operator["closest_m"], distance)

    @callback
    def async_flights(
        self,
        days: int | None = None,
        limit: int | None = None,
        operator: str | None = None,
        only_returning: bool = False,
    ) -> list[dict[str, Any]]:
        """Recorded flights, newest first. Never contains a phone number."""
        flights = self._within(days)

        if operator is not None:
            flights = [f for f in flights if f.get("operator") == operator]

        if only_returning:
            flights = [
                flight
                for flight in flights
                if (key := flight.get("operator"))
                and self._operators.get(key, {}).get("flights", 0) > 1
            ]

        flights.sort(key=lambda flight: flight["last_seen"], reverse=True)
        if limit is not None:
            flights = flights[:limit]
        return [dict(flight) for flight in flights]

    @callback
    def async_operators(
        self, days: int | None = None, min_flights: int = 1
    ) -> list[dict[str, Any]]:
        """Operator summaries — the returning-visitor view, WITHOUT phone numbers.

        Browsing history must stay free of personal data: a response variable can be
        captured into a template sensor, and from there into the recorder database.
        Use `async_operator` for the one case that needs the number.
        """
        cutoff = self._cutoff(days)
        return sorted(
            (
                {
                    "operator": operator["operator"],
                    "flights": operator["flights"],
                    "first_seen": operator["first_seen"],
                    "last_seen": operator["last_seen"],
                    "closest_m": operator["closest_m"],
                    "has_phone": operator.get("number") is not None,
                }
                for operator in self._operators.values()
                if operator["flights"] >= min_flights
                and (cutoff is None or operator["last_seen"] >= cutoff)
            ),
            key=lambda row: (-row["flights"], row["last_seen"]),
        )

    @callback
    def async_operator(self, operator_key: str) -> dict[str, Any] | None:
        """The ONLY method that returns a phone number. Keep it that way."""
        operator = self._operators.get(operator_key)
        if operator is None:
            return None

        number = operator.get("number")
        country = operator.get("country_code")
        return {
            "operator": operator["operator"],
            "flights": operator["flights"],
            "first_seen": operator["first_seen"],
            "last_seen": operator["last_seen"],
            "closest_m": operator["closest_m"],
            "country_code": country,
            "number": number,
            "phone": f"{country} {number}".strip() if number else None,
        }

    @callback
    def async_last_flight(self) -> dict[str, Any] | None:
        """The newest flight, enriched with what is known about its operator.

        One of the two methods that can return a phone number, and only when phone
        storage is on. It feeds the "last flight" sensor, so whatever it returns
        lands in entity attributes and therefore in the recorder database.
        """
        flights = self.async_flights(limit=1)
        if not flights:
            return None

        flight = flights[0]
        operator = (
            self.async_operator(flight["operator"]) if flight.get("operator") else None
        )
        if operator is None:
            flight["operator_flights"] = None
            flight["operator_first_seen"] = None
            flight["operator_last_seen"] = None
            flight["operator_closest_m"] = None
            flight["returning"] = False
            flight["phone"] = None
            return flight

        flight["operator_flights"] = operator["flights"]
        flight["operator_first_seen"] = operator["first_seen"]
        flight["operator_last_seen"] = operator["last_seen"]
        flight["operator_closest_m"] = operator["closest_m"]
        flight["returning"] = operator["flights"] > 1
        flight["phone"] = operator["phone"]
        return flight

    @callback
    def async_counters(self) -> tuple[int, int]:
        """(flights in the recent window, operators seen more than once)."""
        return (
            len(self._within(HISTORY_RECENT_DAYS)),
            len(self.async_operators(min_flights=2)),
        )

    async def async_purge(
        self, older_than_days: int | None = None, operator: str | None = None
    ) -> int:
        """Delete history. Without arguments, deletes everything."""
        before = len(self._flights)

        if operator is not None:
            self._flights = {
                fid: flight
                for fid, flight in self._flights.items()
                if flight.get("operator") != operator
            }
            self._operators.pop(operator, None)
        elif older_than_days is None:
            self._flights.clear()
            self._operators.clear()
        else:
            keep = {flight["id"] for flight in self._within(older_than_days)}
            self._flights = {
                fid: flight for fid, flight in self._flights.items() if fid in keep
            }

        self._drop_orphaned_operators()
        removed = before - len(self._flights)
        await self._store.async_save(self._as_dict())
        return removed

    def _cutoff(self, days: int | None) -> str | None:
        # Every timestamp is a UTC isoformat string, so lexicographic order is
        # chronological order and the read path never parses anything.
        if days is None:
            return None
        return (dt_util.utcnow() - timedelta(days=days)).isoformat()

    def _within(self, days: int | None) -> list[dict[str, Any]]:
        cutoff = self._cutoff(days)
        if cutoff is None:
            return list(self._flights.values())
        return [f for f in self._flights.values() if f["last_seen"] >= cutoff]

    def _drop_orphaned_operators(self) -> None:
        alive = {
            flight["operator"] for flight in self._flights.values() if flight.get("operator")
        }
        for key in [k for k in self._operators if k not in alive]:
            del self._operators[key]

    def _prune(self) -> bool:
        """Apply retention and the hard caps. True when something was dropped.

        The caps are not decoration: the radius picker is unbounded, so a 100 km
        radius would otherwise turn this file into thousands of records a day.
        """
        before = len(self._flights)

        keep = {flight["id"] for flight in self._within(self.retention_days)}
        if len(keep) != before:
            self._flights = {
                fid: flight for fid, flight in self._flights.items() if fid in keep
            }

        if len(self._flights) > HISTORY_MAX_FLIGHTS:
            newest = sorted(
                self._flights.values(), key=lambda f: f["last_seen"], reverse=True
            )[:HISTORY_MAX_FLIGHTS]
            self._flights = {flight["id"]: flight for flight in newest}

        changed = len(self._flights) != before
        if changed:
            self._drop_orphaned_operators()

        if len(self._operators) > HISTORY_MAX_OPERATORS:
            newest_ops = sorted(
                self._operators.values(), key=lambda o: o["last_seen"], reverse=True
            )[:HISTORY_MAX_OPERATORS]
            self._operators = {op["operator"]: op for op in newest_ops}
            changed = True

        return changed
