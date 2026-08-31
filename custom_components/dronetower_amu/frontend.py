"""Serve and auto-register the DroneTower Lovelace cards.

The registration pattern (static path + add_extra_js_url) is adapted from the
MIT-licensed Dectyr RX-5 integration by Alexandre Thomas
(https://github.com/DECTYR/ha-integration).
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_FRONTEND_FLAG = f"{DOMAIN}_frontend_registered"

URL_BASE = f"/{DOMAIN}_static"
CARD_FILES = ("dronetower-map-card.js", "dronetower-surveillance-card.js")


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the frontend bundle and preload the card modules (once per HA process)."""
    if hass.data.get(_FRONTEND_FLAG):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    cards = [name for name in CARD_FILES if (frontend_dir / name).is_file()]
    if not cards:
        _LOGGER.warning("No DroneTower Lovelace cards found in %s", frontend_dir)
        return

    try:
        # Both must be up before we can serve a static path and inject a JS module;
        # they almost always are, so these are no-ops that just guarantee ordering.
        for component in ("http", "frontend"):
            if component not in hass.config.components:
                await async_setup_component(hass, component, {})

        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=False)]
        )
        for name in cards:
            add_extra_js_url(hass, f"{URL_BASE}/{name}")
    except Exception:  # noqa: BLE001 - the cards are optional; never block setup
        _LOGGER.warning("Could not register the DroneTower Lovelace cards", exc_info=True)
        return

    hass.data[_FRONTEND_FLAG] = True
    _LOGGER.info("Registered DroneTower Lovelace cards: %s", ", ".join(cards))
