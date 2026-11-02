"""The radio as a media player: what is on air, transport, volume, stations and lists.

The radio plays its own stations, and (from RL.3) an album, playlist or collection start to end;
Home Assistant controls it like the Lumae app's remote does. Nothing here enters personal
listening history: radio listening is always Stealth.
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
    SearchError,
    SearchMedia,
    SearchMediaQuery,
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
    MEDIA_TYPE_COLLECTION,
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

# Media's folders for a radio that plays lists, each read from the radio a page at a time.
LIST_FOLDERS: dict[str, str] = {
    "albums": "album",
    "playlists": "playlist",
    "collections": "collection",
}
FOLDER_TITLES: dict[str, str] = {
    "stations": "Stations",
    "albums": "Albums",
    "playlists": "Playlists",
    "collections": "Collections",
}
LIST_CLASSES: dict[str, MediaClass] = {
    "album": MediaClass.ALBUM,
    "playlist": MediaClass.PLAYLIST,
    "collection": MediaClass.PLAYLIST,
}
LIST_TYPES: dict[str, str] = {
    "album": MediaType.ALBUM,
    "playlist": MediaType.PLAYLIST,
    "collection": MEDIA_TYPE_COLLECTION,
}
BROWSE_PAGE = 64
SEARCH_LIMIT = 20

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
    # The card's working data changes with every track; history keeps only what played.
    _unrecorded_attributes = frozenset(
        {
            "stations",
            "list",
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
        # Whether the next album, playlist or collection played is shuffled (RL.6).
        self._shuffle_lists = False

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
    def _list(self) -> dict[str, Any] | None:
        return model.list_on_air(self._status)

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = FEATURES
        # Search finds albums, playlists and collections; Previous goes back within a list.
        if model.plays_lists(self._status):
            features |= MediaPlayerEntityFeature.SEARCH_MEDIA
        if self._list is not None:
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        # Shuffle is for the next album, playlist or collection played (RL.6).
        if model.shuffles_lists(self._status):
            features |= MediaPlayerEntityFeature.SHUFFLE_SET
        return features

    @property
    def shuffle(self) -> bool | None:
        return self._shuffle_lists if model.shuffles_lists(self._status) else None

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
    def media_playlist(self) -> str | None:
        return self._list["name"] if self._list else None

    @property
    def source(self) -> str | None:
        # A list plays instead of a station: its name, as on the Lumae app's remote.
        if self._list:
            return self._list["name"]
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
        on_air = self._list
        return {
            "radio_state": model.playback_state(status),
            "station_id": model.station_id(status),
            "plays_lists": model.plays_lists(status),
            "list": {**on_air, "place": model.list_place(on_air)} if on_air else None,
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

    async def async_media_previous_track(self) -> None:
        # Within a list: the song's start after 15 seconds, else the song before.
        await self.coordinator.async_command("previous")

    async def async_set_shuffle(self, shuffle: bool) -> None:
        # The radio works a shuffled order out once at Play, so this is for the next list.
        self._shuffle_lists = shuffle
        self.async_write_ha_state()

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
        if (chosen := _list_media(media_type, media_id)) is not None:
            if not model.plays_lists(self._status):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="lists_unsupported"
                )
            kind, identifier = chosen
            shuffled = self._shuffle_lists and model.shuffles_lists(self._status)
            await self.coordinator.async_command(
                "play",
                list={"kind": kind, "id": identifier},
                **({"order": "shuffle"} if shuffled else {}),
            )
            return
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
        lists = model.plays_lists(self._status)
        # A radio that plays lists opens on its folders; an older one on its stations.
        if lists and media_content_id in (None, "", "root"):
            return BrowseMedia(
                media_class=MediaClass.DIRECTORY,
                media_content_id="root",
                media_content_type="root",
                title=self.coordinator.config_entry.title,
                can_play=False,
                can_expand=True,
                can_search=True,
                children_media_class=MediaClass.DIRECTORY,
                children=[_folder(folder) for folder in FOLDER_TITLES],
            )
        if media_content_id in (None, "", "stations"):
            return self._browse_stations(searchable=lists)
        folder, _, cursor = (media_content_id or "").partition(":")
        if lists and folder in LIST_FOLDERS:
            return await self._browse_lists(folder, cursor or None)
        raise BrowseError(f"Unknown item: {media_content_id}")

    def _browse_stations(self, *, searchable: bool) -> BrowseMedia:
        stations = model.station_summaries(self.coordinator.data.stations)
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id="stations",
            media_content_type="stations",
            title="Stations",
            can_play=False,
            can_expand=True,
            can_search=searchable,
            children_media_class=MediaClass.CHANNEL,
            children=[_station_media(station) for station in stations],
        )

    async def _browse_lists(self, folder: str, cursor: str | None) -> BrowseMedia:
        """One page of the radio's albums, playlists or collections, then More."""
        kind = LIST_FOLDERS[folder]
        try:
            data = await self.coordinator.client.catalogue(
                kind, cursor=cursor, limit=BROWSE_PAGE
            )
        except RadioError as err:
            raise BrowseError(model.refusal_text(err.code)) from err
        items, next_cursor = model.catalogue_page(data, kind)
        children = [_list_item(kind, item) for item in items]
        if next_cursor:
            children.append(
                BrowseMedia(
                    media_class=MediaClass.DIRECTORY,
                    media_content_id=f"{folder}:{next_cursor}",
                    media_content_type=folder,
                    title=f"More {FOLDER_TITLES[folder].lower()}",
                    can_play=False,
                    can_expand=True,
                )
            )
        return BrowseMedia(
            media_class=MediaClass.DIRECTORY,
            media_content_id=f"{folder}:{cursor}" if cursor else folder,
            media_content_type=folder,
            title=FOLDER_TITLES[folder],
            can_play=False,
            can_expand=True,
            can_search=True,
            children_media_class=LIST_CLASSES[kind],
            children=children,
        )

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Stations by name, and the radio's albums, playlists and collections."""
        if not model.plays_lists(self._status):
            raise SearchError(
                "Update Lumae Radio to search its albums, playlists and collections."
            )
        text = query.search_query.strip()
        if not text:
            return SearchMedia(result=[])
        kinds, stations = _search_targets(query)
        result: list[BrowseMedia] = []
        if stations:
            needle = text.casefold()
            result.extend(
                _station_media(station)
                for station in model.station_summaries(self.coordinator.data.stations)
                if needle in station["name"].casefold()
            )
        failures: list[RadioError] = []
        for kind in kinds:
            try:
                data = await self.coordinator.client.catalogue(
                    kind, text, limit=SEARCH_LIMIT
                )
            except RadioError as err:
                # Collections switched off, say, still leave albums and playlists to find.
                failures.append(err)
                continue
            items, _ = model.catalogue_page(data, kind)
            result.extend(_list_item(kind, item) for item in items)
        if kinds and len(failures) == len(kinds) and not result:
            raise SearchError(model.refusal_text(failures[0].code))
        return SearchMedia(result=result)

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


def _folder(folder: str) -> BrowseMedia:
    # Only a radio that plays lists has folders, and it searches each one.
    return BrowseMedia(
        media_class=MediaClass.DIRECTORY,
        media_content_id=folder,
        media_content_type=folder,
        title=FOLDER_TITLES[folder],
        can_play=False,
        can_expand=True,
        can_search=True,
    )


def _station_media(station: dict[str, Any]) -> BrowseMedia:
    return BrowseMedia(
        media_class=MediaClass.CHANNEL,
        media_content_id=f"{STATION_PREFIX}{station['id']}",
        media_content_type=MEDIA_TYPE_STATION,
        title=station["name"],
        can_play=True,
        can_expand=False,
    )


def _list_item(kind: str, item: dict[str, Any]) -> BrowseMedia:
    return BrowseMedia(
        media_class=LIST_CLASSES[kind],
        media_content_id=f"{kind}:{item['id']}",
        media_content_type=LIST_TYPES[kind],
        title=model.catalogue_title(kind, item),
        can_play=True,
        can_expand=False,
    )


def _list_media(media_type: MediaType | str, media_id: str) -> tuple[str, str] | None:
    """An album, playlist or collection to play: `album:<id>`, or the kind as the type.

    None for a station. An empty ID is no list at all.
    """
    for kind in model.LIST_KINDS:
        identifier = (
            media_id.removeprefix(f"{kind}:")
            if media_id.startswith(f"{kind}:")
            else None
        )
        if identifier is None and str(media_type) == LIST_TYPES[kind]:
            identifier = media_id
        if identifier is not None:
            if not identifier:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="unknown_list"
                )
            return kind, identifier
    return None


def _search_targets(query: SearchMediaQuery) -> tuple[list[str], bool]:
    """Which lists to search, and whether stations too.

    From the folder searched in Media (its content type), else the query's type or classes.
    """
    content_type = str(query.media_content_type) if query.media_content_type else None
    if content_type in LIST_FOLDERS:
        return [LIST_FOLDERS[content_type]], False
    if content_type in (MEDIA_TYPE_STATION, "stations"):
        return [], True
    if content_type in LIST_TYPES.values():
        return [
            kind for kind, value in LIST_TYPES.items() if value == content_type
        ], False
    classes = set(query.media_filter_classes or [])
    if not classes:
        return list(model.LIST_KINDS), True
    kinds = [kind for kind in model.LIST_KINDS if LIST_CLASSES[kind] in classes]
    return kinds, MediaClass.CHANNEL in classes
