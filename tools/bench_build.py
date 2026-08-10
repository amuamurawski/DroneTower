"""Compare the per-event cost before and after caching per check-in.

    .venv/bin/python tools/bench_build.py

The nationwide broadcast delivers roughly one event per second. The old path
re-parsed every end time and re-ran a geodesic distance for every check-in on each
of them; the new one does that work once per check-in, when it arrives.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from homeassistant.util import dt as dt_util
from homeassistant.util.location import distance as geo_distance

HOME = (52.2297, 21.0122)
SNAPSHOT = Path("work/analysis/checkins_sample.json")
API = "https://bff-drone-tower.uav.pansa.pl/api/checkins"
CT = "application/vnd.pansa.bff-drone-tower.v1+json"


def load() -> list[dict]:
    if SNAPSHOT.exists():
        return json.loads(SNAPSHOT.read_text())["checkins"]
    request = urllib.request.Request(API, headers={"content-type": CT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["checkins"]


def timed(label: str, fn, repeats: int) -> float:
    start = time.perf_counter()
    for _ in range(repeats):
        fn()
    per = (time.perf_counter() - start) / repeats
    print(f"  {label:<40} {per * 1000:8.4f} ms")
    return per


def main() -> None:
    checkins = load()
    n = len(checkins)

    ends = [c.get("endDateTime") for c in checkins]
    centres = [
        (c["flightArea"]["center"]["latitude"], c["flightArea"]["center"]["longitude"])
        for c in checkins
    ]
    print(f"Zgłoszeń w próbce: {n}\n")

    def old_path() -> None:
        """Re-parse and re-measure everything, as before."""
        cutoff = dt_util.utcnow()
        for value in ends:
            end = dt_util.parse_datetime(value)
            _ = end is not None and end < cutoff
        out = []
        for lat, lon in centres:
            d = geo_distance(HOME[0], HOME[1], lat, lon)
            if d is not None and d <= 5000:
                out.append(d)
        out.sort()

    # What the new path keeps around between events.
    expiry = [dt_util.parse_datetime(v) for v in ends]
    derived = [
        {"distance_to_area_m": geo_distance(HOME[0], HOME[1], lat, lon)}
        if geo_distance(HOME[0], HOME[1], lat, lon) <= 5000
        else None
        for lat, lon in centres
    ]

    def new_path() -> None:
        """One check-in parsed and measured, then a cheap sweep of the cache."""
        dt_util.parse_datetime(ends[0])
        geo_distance(HOME[0], HOME[1], *centres[0])
        cutoff = dt_util.utcnow()
        _ = [i for i, end in enumerate(expiry) if end is not None and end < cutoff]
        nearby = [e for e in derived if e is not None]
        nearby.sort(key=lambda item: item["distance_to_area_m"])

    print("Koszt obsługi jednego zdarzenia:")
    old = timed("przed zmianą", old_path, 300)
    new = timed("po zmianie", new_path, 2000)

    print(f"\n  przyspieszenie: {old / new:.0f}x")
    for rate, label in ((1.0, "1 zdarzenie/s"),):
        print(f"\n  Przy {label}, obciążenie jednego rdzenia:")
        print(f"    przed: {old * rate * 100:6.3f} %   ({old * rate * 86400:5.0f} s CPU/dobę)")
        print(f"    po:    {new * rate * 100:6.3f} %   ({new * rate * 86400:5.0f} s CPU/dobę)")


if __name__ == "__main__":
    main()
