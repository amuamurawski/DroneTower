"""Constants for the DroneTower-AMU integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "dronetower_amu"

API_BASE = "https://bff-drone-tower.uav.pansa.pl/api"
WS_URL = "wss://bff-drone-tower.uav.pansa.pl/ws"

# The BFF rejects every request without this vendor media type with HTTP 415.
CONTENT_TYPE = "application/vnd.pansa.bff-drone-tower.v1+json"

STOMP_PROTOCOLS = ("v12.stomp", "v11.stomp", "v10.stomp")
TOPIC_ACTIVE_CHECKINS = (
    "/websocket/topic/drone-tower-queue"
    "/drone-tower-active-checkins-topic/broadcast"
)

EVENT_CHECKIN = "CheckinEvent"
EVENT_CHECKIN_FINISHED = "CheckinFinishedEvent"
EVENT_CHECKIN_LOST_CONTROL = "CheckinLostControlEvent"
EVENT_CHECKIN_REFRESH = "CheckinRefreshEvent"

STATUS_CREATED = "CREATED"
STATUS_ACTIVE = "ACTIVE"
STATUS_OVERDUE = "OVERDUE"

# Statuses that mean the flight is over or was refused; never counted as nearby.
TERMINAL_STATUSES = frozenset({"FINISHED", "REJECTED", "CANCELLED"})

CONF_RADIUS = "radius"
CONF_INCLUDE_OVERDUE = "include_overdue"
CONF_INCLUDE_PLANNED = "include_planned"

DEFAULT_NAME = "Drony w okolicy"
DEFAULT_RADIUS = 5000
DEFAULT_INCLUDE_OVERDUE = False
DEFAULT_INCLUDE_PLANNED = True

# Full REST snapshot cadence. The live picture comes from the WebSocket; this only
# heals drift and refreshes the nationwide counter.
RESYNC_INTERVAL = timedelta(minutes=5)

# Check-ins linger in memory only while they can plausibly still be flying.
STALE_AFTER = timedelta(hours=6)

WS_RECEIVE_TIMEOUT = 60
WS_HEARTBEAT_MS = 10000
WS_RETRY_MIN = 5
WS_RETRY_MAX = 300

HA_EVENT_DETECTED = f"{DOMAIN}_drone_detected"
HA_EVENT_CLEARED = f"{DOMAIN}_drone_cleared"

ATTR_DRONES = "drones"
ATTR_TOTAL_ACTIVE = "total_active_in_poland"
