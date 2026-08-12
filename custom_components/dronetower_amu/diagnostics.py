"""Diagnostics for DroneTower-AMU.

Diagnostics get pasted into bug reports, so this file reports counts and nothing
else. In particular it must never touch `coordinator._checkins` — those are the raw
API dicts, which is where the pilots' phone numbers live — and never the history's
operator index.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant

from . import DroneTowerConfigEntry

# The monitored point is the reporter's home address.
TO_REDACT = {CONF_LATITUDE, CONF_LONGITUDE}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DroneTowerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    history = coordinator.history

    recent_flights, returning_operators = (
        history.async_counters() if history is not None else (0, 0)
    )

    return {
        "options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinator": {
            "total_active": data.get("total_active"),
            "nearby": len(data.get("nearby") or []),
            "stream_connected": coordinator.stream_connected,
        },
        "history": {
            # Counts only. The flight list is free of personal data by construction,
            # but it is still a precise log of third parties' flight areas around
            # the reporter's house and adds nothing to a bug report.
            "recent_flights": recent_flights,
            "returning_operators": returning_operators,
            "stores_phone": history.stores_phone if history else None,
            "retention_days": history.retention_days if history else None,
            "salt": "**REDACTED**",
        },
    }
