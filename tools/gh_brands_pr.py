"""Open the home-assistant/brands pull request that makes the icon show up.

    .venv/bin/python tools/gh_brands_pr.py

Forks the repo if needed, pushes the two PNGs onto a branch and opens the PR.
Home Assistant serves integration icons from brands.home-assistant.io, so until
this lands the panel shows "icon not available" no matter what this repo contains.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

UPSTREAM = "home-assistant/brands"
DOMAIN = "dronetower_amu"
BRANCH = f"add-{DOMAIN.replace('_', '-')}"
SOURCE = Path("brands/custom_integrations") / DOMAIN
INTEGRATION_REPO = "https://github.com/amuamurawski/DroneTower"

TITLE = "Add DroneTower-AMU"
BODY = f"""## Proposed change

Adds the icon for the custom integration `{DOMAIN}` (DroneTower-AMU).

The integration surfaces drone flight check-ins registered with PANSA, the Polish
air navigation service provider, as Home Assistant entities around a chosen point.

Repository: {INTEGRATION_REPO}

## Checklist

- [x] The images are PNG.
- [x] The images are trimmed and contain no empty space around the subject.
- [x] The images have a transparent background.
- [x] `icon.png` is 256x256 and `icon@2x.png` is 512x512.
- [x] The artwork is original and uses no Home Assistant branding.
- [x] The directory name matches the integration `domain` in its `manifest.json`.
"""


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


def api(
    method: str, path: str, tok: str, body: dict | None = None, quiet: bool = False
) -> dict | None:
    request = urllib.request.Request(
        f"https://api.github.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "dronetower-amu-brands-pr",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        if quiet:
            return None
        detail = err.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"{method} {path} -> HTTP {err.code}\n{detail}") from err


def main() -> None:
    tok = token()
    me = api("GET", "/user", tok)["login"]
    fork = f"{me}/brands"

    upstream = api("GET", f"/repos/{UPSTREAM}", tok)
    base_branch = upstream["default_branch"]

    if api("GET", f"/repos/{fork}", tok, quiet=True) is None:
        api("POST", f"/repos/{UPSTREAM}/forks", tok, {})
        print(f"fork {fork} tworzony...")
        for _ in range(30):
            time.sleep(4)
            if api("GET", f"/repos/{fork}", tok, quiet=True) is not None:
                break
        else:
            raise SystemExit("Fork nie pojawił się w rozsądnym czasie")
    print(f"fork gotowy: {fork}")

    head_sha = api("GET", f"/repos/{UPSTREAM}/git/ref/heads/{base_branch}", tok)[
        "object"
    ]["sha"]

    existing = api("GET", f"/repos/{fork}/git/ref/heads/{BRANCH}", tok, quiet=True)
    if existing is None:
        api(
            "POST",
            f"/repos/{fork}/git/refs",
            tok,
            {"ref": f"refs/heads/{BRANCH}", "sha": head_sha},
        )
        print(f"gałąź {BRANCH} utworzona na {head_sha[:7]}")
    else:
        print(f"gałąź {BRANCH} już istnieje")

    for name in ("icon.png", "icon@2x.png"):
        path = f"custom_integrations/{DOMAIN}/{name}"
        payload = {
            "message": f"Add {DOMAIN} {name}",
            "content": base64.b64encode((SOURCE / name).read_bytes()).decode(),
            "branch": BRANCH,
        }
        current = api(
            "GET", f"/repos/{fork}/contents/{path}?ref={BRANCH}", tok, quiet=True
        )
        if current:
            payload["sha"] = current["sha"]
        api("PUT", f"/repos/{fork}/contents/{path}", tok, payload)
        print(f"wysłano {path}")

    open_prs = api(
        "GET", f"/repos/{UPSTREAM}/pulls?head={me}:{BRANCH}&state=open", tok
    )
    if open_prs:
        print("PR już otwarty:", open_prs[0]["html_url"])
        return

    pull = api(
        "POST",
        f"/repos/{UPSTREAM}/pulls",
        tok,
        {
            "title": TITLE,
            "head": f"{me}:{BRANCH}",
            "base": base_branch,
            "body": BODY,
            "maintainer_can_modify": True,
        },
    )
    print("PR otwarty:", pull["html_url"])


if __name__ == "__main__":
    main()
