"""Verify every mdi: icon the integration uses actually exists.

    .venv/bin/python tools/check_icons.py

A name that is not in the set renders as nothing at all — no error, no fallback,
just a blank space where the icon should be. That is how `mdi:account-repeat`
shipped in 1.2.0. Needs network, so it is a dev check rather than a CI job.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

META = "https://raw.githubusercontent.com/Templarian/MaterialDesign/master/meta.json"
SOURCE = Path("custom_components/dronetower_amu")


def main() -> int:
    used: dict[str, list[str]] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        for name in re.findall(r'"mdi:([a-z0-9-]+)"', path.read_text(encoding="utf-8")):
            used.setdefault(name, []).append(f"{path.name}")

    if not used:
        print("nie znaleziono żadnych ikon")
        return 1

    with urllib.request.urlopen(META, timeout=60) as response:
        known = {icon["name"] for icon in json.load(response)}

    missing = False
    for name in sorted(used):
        ok = name in known
        missing |= not ok
        mark = "OK        " if ok else "NIE ISTNIEJE"
        print(f"  {mark} mdi:{name:<24} {', '.join(sorted(set(used[name])))}")

    print(f"\n{len(used)} ikon sprawdzonych wobec {len(known)} z zestawu MDI")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
