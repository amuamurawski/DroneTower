"""Smoke test: run the integration's real client against the production backend.

    python tools/live_check.py 52.2297 21.0122 5000

Fetches one snapshot, then listens to the live feed for 20 seconds and reports what
would have reached the given point. No credentials, no writes.
"""

from __future__ import annotations

import asyncio
import sys

import aiohttp

sys.path.insert(0, ".")

from custom_components.dronetower_amu.api import DroneTowerClient  # noqa: E402


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 6371000 * 2 * asin(sqrt(a))


def edge_distance(checkin: dict, lat: float, lon: float) -> float | None:
    center = (checkin.get("flightArea") or {}).get("center") or {}
    if center.get("latitude") is None:
        return None
    to_center = haversine(lat, lon, center["latitude"], center["longitude"])
    return max(0.0, to_center - (checkin["flightArea"].get("radius") or 0.0))


async def main() -> None:
    lat = float(sys.argv[1]) if len(sys.argv) > 1 else 52.2297
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else 21.0122
    radius = float(sys.argv[3]) if len(sys.argv) > 3 else 5000

    async with aiohttp.ClientSession() as session:
        client = DroneTowerClient(session)

        checkins = await client.async_get_checkins()
        print(f"REST snapshot: {len(checkins)} active check-ins nationwide")

        statuses: dict[str, int] = {}
        nearby = []
        for checkin in checkins:
            statuses[checkin.get("status", "?")] = (
                statuses.get(checkin.get("status", "?"), 0) + 1
            )
            distance = edge_distance(checkin, lat, lon)
            if distance is not None and distance <= radius:
                nearby.append((distance, checkin))

        print(f"  statuses: {statuses}")
        print(f"  within {radius:.0f} m of {lat},{lon}: {len(nearby)}")
        for distance, checkin in sorted(nearby)[:5]:
            area = checkin["flightArea"]
            print(
                f"    {distance:7.0f} m  {checkin['status']:<8} "
                f"r={area.get('radius')} h={area.get('maxHeight')} "
                f"until {checkin.get('endDateTime')}"
            )

        print("\nListening on the live feed for 20 s...")
        events: dict[str, int] = {}

        def on_event(event_type: str, checkin: dict) -> None:
            events[event_type] = events.get(event_type, 0) + 1
            distance = edge_distance(checkin, lat, lon)
            if distance is not None and distance <= radius:
                print(f"  NEARBY {event_type}: {distance:.0f} m  {checkin['status']}")

        try:
            await asyncio.wait_for(
                client.async_run_stream(on_event, lambda: print("  STOMP connected")),
                timeout=20,
            )
        except TimeoutError:
            pass

        total = sum(events.values())
        print(f"\nLive feed: {total} events in 20 s -> {events}")
        print("OK" if total else "No events observed (quiet period?)")


if __name__ == "__main__":
    asyncio.run(main())
