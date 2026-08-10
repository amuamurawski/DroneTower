"""One-off GitHub housekeeping: repo metadata and the release for the current tag.

    .venv/bin/python tools/gh_setup.py

Reads the token from git's credential helper, so it works wherever `git push`
already works. HACS refuses a repository without a description and topics.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "amuamurawski"
REPO = "DroneTower"
TAG = "v" + json.loads(
    Path("custom_components/dronetower_amu/manifest.json").read_text()
)["version"]

DESCRIPTION = (
    "Integracja Home Assistant pokazująca zgłoszone loty dronów w okolicy "
    "(PANSA DroneTower) wraz z dokumentacją odtworzonego API"
)
TOPICS = [
    "home-assistant",
    "homeassistant",
    "hacs",
    "custom-integration",
    "drones",
    "uav",
    "pansa",
    "poland",
    "reverse-engineering",
]


def token() -> str:
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line[len("password=") :]
    raise SystemExit("Nie znaleziono tokena w credential helperze")


def api(method: str, path: str, tok: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "dronetower-amu-setup",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"{method} {path} -> HTTP {err.code}\n{detail}") from err


def changelog_section(version: str) -> str:
    text = Path("CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(
        rf"^## \[?{re.escape(version)}\]?.*?$(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise SystemExit(f"Brak sekcji {version} w CHANGELOG.md")
    return match.group(1).strip()


def main() -> None:
    tok = token()

    api("PATCH", f"/repos/{OWNER}/{REPO}", tok, {"description": DESCRIPTION})
    print("opis ustawiony")

    api("PUT", f"/repos/{OWNER}/{REPO}/topics", tok, {"names": TOPICS})
    print("tematy ustawione:", ", ".join(TOPICS))

    version = TAG.lstrip("v")
    try:
        existing = api("GET", f"/repos/{OWNER}/{REPO}/releases/tags/{TAG}", tok)
        print(f"release {TAG} już istnieje: {existing['html_url']}")
        return
    except SystemExit:
        pass

    release = api(
        "POST",
        f"/repos/{OWNER}/{REPO}/releases",
        tok,
        {
            "tag_name": TAG,
            "name": version,
            "body": changelog_section(version),
            "draft": False,
            "prerelease": False,
        },
    )
    print("release utworzony:", release["html_url"])


if __name__ == "__main__":
    main()
