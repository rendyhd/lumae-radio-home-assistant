"""Constants for the Lumae Radio integration."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "lumae_radio"
LOGGER = logging.getLogger(__package__)

# The radio's web address (its first allowed origin), the host reached for it (an IP from
# discovery, or the origin's own name), its pinned certificate and the API key.
CONF_ORIGIN: Final = "origin"
CONF_CONNECT_HOST: Final = "connect_host"
CONF_FINGERPRINT: Final = "fingerprint"
CONF_API_KEY: Final = "api_key"

SCOPE_CONTROL: Final = "control"
SCOPE_STATIONS: Final = "stations"

# The card ships with the integration and is served from here.
FRONTEND_URL: Final = "/lumae_radio_static"
CARD_FILE: Final = "lumae-radio-card.js"

SERVICE_STEER_TRACK: Final = "steer_track"
ATTR_CHOICE: Final = "choice"
ATTR_REST_DAYS: Final = "rest_days"
ATTR_REST_UNTIL: Final = "rest_until"

# Part of each cover's address in Home Assistant; raise it when covers served before were wrong.
ARTWORK_CACHE_VERSION: Final = 2

MEDIA_TYPE_STATION: Final = "station"
STATION_PREFIX: Final = "station:"
# Albums, playlists and collections (RL.11): `album:<id>`, `playlist:<id>`, `collection:<id>`.
MEDIA_TYPE_COLLECTION: Final = "collection"
