"""The radio as a media player: what is on air, transport, volume and stations.

The radio plays its own stations; Home Assistant controls it like the Lumae app's remote does.
Nothing here enters personal listening history: radio listening is always Stealth.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from . import model
from .api import RadioError
from .const import (
    ARTWORK_CACHE_VERSION,
    ATTR_CHOICE,
    ATTR_REST_DAYS,
    ATTR_REST_UNTIL,
    CONF_ORIGIN,
    DOMAIN,
    MEDIA_TYPE_STATION,
    SCOPE_STATIONS,
    SERVICE_STEER_TRACK,
    STATION_PREFIX,
)
from .coordinator import LumaeRadioConfigEntry, LumaeRadioCoordinator
from .entity import LumaeRadioEntity

PARALLEL_UPDATES = 0

STATES = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "buffering": MediaPlayerState.BUFFERING,
    "stopped": MediaPlayerState.IDLE,
    "fault": MediaPlayerState.IDLE,
}

FEATURES = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)

STEER_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_CHOICE): vol.In(list(model.STEER_ACTIONS)),
        vol.Exclusive(ATTR_REST_DAYS, "rest"): vol.All(
            vol.Coerce(float), vol.Range(min=0.01, max=model.MAX_REST_DAYS)
        ),
        vol.Exclusive(ATTR_REST_UNTIL, "rest"): cv.datetime,
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LumaeRadioConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LumaeRadioPlayer(entry.runtime_data)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_STEER_TRACK, STEER_SCHEMA, "async_steer_track"
    )


class LumaeRadioPlayer(LumaeRadioEntity, MediaPlayerEntity):
    """One Lumae Radio."""

    _attr_name = None
    _attr_translation_key = "radio"
    _attr_media_content_type = MediaType.MUSIC
    _attr_media_image_remotely_accessible = False
    _attr_supported_features = FEATURES
    # The card's working data changes with every track; history keeps only what played.
    _unrecorded_attributes = frozenset(
        {
            "stations",
            "standing",
            "selection",
            "health",
            "can_steer",
            "live_updates",
            "web_address",
        }
    )

    def __init__(self, coordinator: LumaeRadioCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.config_entry.unique_id

    @property
    def _status(self) -> dict[str, Any]:
        return self.coordinator.data.status if self.coordinator.data else {}

    @property
    def _track(self) -> dict[str, Any] | None:
        return model.track(self._status)

    @property
    def _station(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        return model.find_station(data.stations, model.station_id(self._status))

    @property
    def state(self) -> MediaPlayerState | None:
        if self.coordinator.data is None:
            return None
        return STATES[model.playback_state(self._status)]

    @property
    def media_content_id(self) -> str | None:
        return self._track["id"] if self._track else None

    @property
    def media_title(self) -> str | None:
        if self._track is None:
            return None
        return self._track.get("title") or "Untitled track"

    @property
    def media_artist(self) -> str | None:
        return (self._track or {}).get("artist") or None

    @property
    def media_album_name(self) -> str | None:
        return (self._track or {}).get("album") or None

    @property
    def media_duration(self) -> float | None:
        return model.duration_seconds(self._status)

    @property
    def media_position(self) -> float | None:
        return model.position_seconds(self._status)

    @property
    def media_position_updated_at(self) -> datetime | None:
        if self.coordinator.data is None or self.media_position is None:
            return None
        return self.coordinator.data.read_at

    @property
    def media_image_hash(self) -> str | None:
        artwork = self._artwork_id
        # Home Assistant's image proxy lets browsers keep a cover for an hour under this key;
        # the suffix moves past covers 0.1.0 cut short.
        return f"{artwork}.{ARTWORK_CACHE_VERSION}" if artwork else None

    @property
    def _artwork_id(self) -> str | None:
        artwork = (self._track or {}).get("artworkId")
        return artwork if isinstance(artwork, str) and artwork else None

    @property
    def volume_level(self) -> float | None:
        return model.volume(self._status)

    @property
    def source(self) -> str | None:
        return self._station.get("name") if self._station else None

    @property
    def source_list(self) -> list[str]:
        data = self.coordinator.data
        return (
            [station["name"] for station in model.station_summaries(data.stations)]
            if data
            else []
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        track = self._track
        station = self._station
        return {
            "radio_state": model.playback_state(status),
            "station_id": model.station_id(status),
            "station_mode": model.energy_mode(station) if station else None,
            "track_id": track["id"] if track else None,
            "stations": model.station_summaries(self.coordinator.data.stations)
            if self.coordinator.data
            else [],
            "standing": model.standing(station, track["id"] if track else None),
            "selection": model.selection(status),
            "health": model.health(status),
            "can_steer": SCOPE_STATIONS in self.coordinator.scopes,
            "live_updates": self.coordinator.events_connected,
            "web_address": self.coordinator.config_entry.data[CONF_ORIGIN],
        }

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        if (artwork := self._artwork_id) is None:
            return None, None
        try:
            return await self.coordinator.client.artwork(artwork)
        except RadioError:
            return None, None

    # ── Transport ────────────────────────────────────────────────────────

    async def async_media_play(self) -> None:
        status = self._status
        command = model.main_command(status)
        if command == "play":
            await self.coordinator.async_command(
                "play", stationId=model.station_id(status)
            )
        elif command == "resume":
            await self.coordinator.async_command("resume")
        elif model.playback_state(status) not in ("playing", "buffering"):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="choose_station"
            )

    async def async_media_pause(self) -> None:
        await self.coordinator.async_command("pause")

    async def async_media_stop(self) -> None:
        await self.coordinator.async_command("stop")

    async def async_media_next_track(self) -> None:
        await self.coordinator.async_command("skip")

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.async_command(
            "volume", volume=round(min(1, max(0, volume)), 2)
        )

    # ── Stations ─────────────────────────────────────────────────────────

    async def async_select_source(self, source: str) -> None:
        stations = model.station_summaries(self.coordinator.data.stations)
        match = next(
            (station for station in stations if station["name"] == source), None
        )
        if match is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_station",
                translation_placeholders={"station": source},
            )
        await self.coordinator.async_command("play", stationId=match["id"])

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        station_id = media_id.removeprefix(STATION_PREFIX)
        if model.find_station(self.coordinator.data.stations, station_id) is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_station",
                translation_placeholders={"station": media_id},
            )
        await self.coordinator.async_command("play", stationId=station_id)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        if media_content_id not in (None, "", "stations"):
            raise BrowseError(f"Unknown item: {media_content_id}")
        stations = model.station_summaries(self.coordinator.data.stations)
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id="stations",
            media_content_type="stations",
            title="Stations",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.CHANNEL,
            children=[
                BrowseMedia(
                    media_class=MediaClass.CHANNEL,
                    media_content_id=f"{STATION_PREFIX}{station['id']}",
                    media_content_type=MEDIA_TYPE_STATION,
                    title=station["name"],
                    can_play=True,
                    can_expand=False,
                )
                for station in stations
            ],
        )

    # ── Steering the playing track ───────────────────────────────────────

    async def async_steer_track(
        self,
        choice: str,
        rest_days: float | None = None,
        rest_until: datetime | None = None,
    ) -> None:
        await self.coordinator.async_steer(
            choice, rest_days=rest_days, rest_until=rest_until
        )
