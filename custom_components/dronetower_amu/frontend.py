"""Serve and auto-register the DroneTower Lovelace map card.

The registration pattern (static path + add_extra_js_url) is adapted from the
MIT-licensed Dectyr RX-5 integration by Alexandre Thomas
(https://github.com/DECTYR/ha-integration).
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_FRONTEND_FLAG = f"{DOMAIN}_frontend_registered"

URL_BASE = f"/{DOMAIN}_static"
CARD_FILENAME = "dronetower-map-card.js"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the frontend bundle and preload the card module (once per HA process)."""
    if hass.data.get(_FRONTEND_FLAG):
        return

    frontend_dir = Path(__file__).parent / "frontend"
    card_path = frontend_dir / CARD_FILENAME
    if not card_path.is_file():
        _LOGGER.warning("DroneTower map card not found at %s", card_path)
        return

    try:
        if "http" not in hass.config.components:
            await async_setup_component(hass, "http", {})

        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(frontend_dir), cache_headers=False)]
        )

        if DATA_EXTRA_MODULE_URL in hass.data:
            add_extra_js_url(hass, f"{URL_BASE}/{CARD_FILENAME}")
        else:
            _LOGGER.debug(
                "Frontend module loader not ready; the card is served at %s/%s but was "
                "not auto-injected. Add it under Settings → Dashboards → Resources.",
                URL_BASE,
                CARD_FILENAME,
            )
    except Exception:  # noqa: BLE001 - the card is optional; never block setup
        _LOGGER.warning("Could not register the DroneTower map card", exc_info=True)
        return

    hass.data[_FRONTEND_FLAG] = True
    _LOGGER.info("Registered the DroneTower map card (%s)", CARD_FILENAME)
