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
CONF_HISTORY_DAYS = "history_days"
CONF_STORE_PHONE = "store_phone_numbers"

DEFAULT_NAME = "Drony w okolicy"
DEFAULT_RADIUS = 5000
DEFAULT_INCLUDE_OVERDUE = False
DEFAULT_INCLUDE_PLANNED = True
DEFAULT_HISTORY_DAYS = 365
# Off by default: the pilot's number is personal data, and a fresh install should
# never start collecting it without the owner deciding to.
DEFAULT_STORE_PHONE = False

# Full REST snapshot cadence. The live picture comes from the WebSocket; this only
# heals drift and refreshes the nationwide counter.
RESYNC_INTERVAL = timedelta(minutes=5)

# Check-ins linger in memory only while they can plausibly still be flying.
STALE_AFTER = timedelta(hours=6)

WS_RECEIVE_TIMEOUT = 60
WS_HEARTBEAT_MS = 10000
WS_RETRY_MIN = 5
WS_RETRY_MAX = 300

# A socket that connects and drops straight away must not reset the backoff, or a
# flaky link turns into a reconnect-and-resync loop every few seconds. Only a
# session that lasted this long counts as healthy.
WS_STABLE_AFTER = 60

HA_EVENT_DETECTED = f"{DOMAIN}_drone_detected"
HA_EVENT_CLEARED = f"{DOMAIN}_drone_cleared"
HA_EVENT_KNOWN_OPERATOR = f"{DOMAIN}_known_operator"

ATTR_DRONES = "drones"
ATTR_TOTAL_ACTIVE = "total_active_in_poland"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.history"
# The radius picker is unbounded, so someone monitoring 100 km would collect
# thousands of flights a day. These caps are what stops the file growing without
# limit.
HISTORY_MAX_FLIGHTS = 5000
HISTORY_MAX_OPERATORS = 2000
# The history barely changes, so batch writes rather than hitting the disk on every
# arrival. Store flushes anything pending on Home Assistant shutdown.
HISTORY_SAVE_DELAY = 30
# Window for the "flights recently" sensor.
HISTORY_RECENT_DAYS = 30
# A flight drifting across the radius edge — or every airborne flight right after a
# restart — must not be counted as a fresh visit.
RE_ENTRY_GRACE = timedelta(minutes=15)

SERVICE_GET_HISTORY = "get_history"
SERVICE_GET_OPERATORS = "get_operators"
SERVICE_GET_OPERATOR = "get_operator"
SERVICE_PURGE_HISTORY = "purge_history"
