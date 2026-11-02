"""The radio as a media player, against the radio's real HTTPS boundary."""

from __future__ import annotations

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_SHUFFLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MP_DOMAIN,
    SERVICE_PLAY_MEDIA,
    SERVICE_SELECT_SOURCE,
    BrowseError,
    MediaClass,
    MediaPlayerEntityFeature,
    SearchError,
    SearchMediaQuery,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_PREVIOUS_TRACK,
    SERVICE_MEDIA_STOP,
    SERVICE_SHUFFLE_SET,
    SERVICE_VOLUME_SET,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_component import async_update_entity
import pytest

from custom_components.lumae_radio.const import DOMAIN

from .conftest import Radio, wait_for

ENTITY = "media_player.lumae_radio"


@pytest.fixture
async def setup(hass: HomeAssistant, radio: Radio, make_entry, frontend):
    async def start(key: str = "full", named: bool = False):
        entry = make_entry(key, named)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    started = []

    async def run(*args, **kwargs):
        entry = await start(*args, **kwargs)
        started.append(entry)
        return entry

    yield run
    for entry in started:
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def call(
    hass: HomeAssistant, service: str, data: dict | None = None, domain: str = MP_DOMAIN
):
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: ENTITY, **(data or {})}, blocking=True
    )


def attrs(hass: HomeAssistant) -> dict:
    return hass.states.get(ENTITY).attributes


async def test_shows_what_is_on_air(
    hass: HomeAssistant, setup, frontend, radio: Radio
) -> None:
    await setup()
    state = hass.states.get(ENTITY)
    assert state.state == STATE_PLAYING
    assert state.attributes["media_title"] == "Holocene"
    assert state.attributes["media_artist"] == "Bon Iver"
    assert state.attributes["media_duration"] == 336
    assert state.attributes["source"] == "Morning drift"
    assert state.attributes["source_list"] == [
        "Morning drift",
        "Deep focus",
        "Late night",
    ]
    assert state.attributes["volume_level"] == 0.62
    assert state.attributes["entity_picture"].startswith(
        f"/api/media_player_proxy/{ENTITY}"
    )
    assert state.attributes["radio_state"] == "playing"
    assert state.attributes["station_mode"] == "daily"
    assert state.attributes["selection"]["fit"] == 0.87
    assert state.attributes["standing"] == {
        "preference": 0,
        "rest_until_ms": None,
        "banned": False,
    }
    assert state.attributes["can_steer"] is True
    assert [station["preparation"] for station in state.attributes["stations"]] == [
        "ready",
        "ready",
        "needed",
    ]
    frontend.assert_called_once()
    assert "/lumae_radio_static/lumae-radio-card.js?v=" in frontend.call_args.args[1]
    hass.http.async_register_static_paths.assert_awaited_once()


async def test_cover_comes_through_home_assistant(hass: HomeAssistant, setup) -> None:
    await setup()
    entity = hass.data[MP_DOMAIN].get_entity(ENTITY)
    body, content_type = await entity.async_get_media_image()
    assert content_type == "image/png" and body.startswith(b"\x89PNG")
    assert body.endswith(b"IEND\xaeB`\x82")
    assert (
        hass.states.get(ENTITY)
        .attributes["entity_picture"]
        .endswith("&cache=trk-holocene.2")
    )


async def test_transport(hass: HomeAssistant, setup) -> None:
    await setup(named=True)
    await call(hass, SERVICE_MEDIA_PAUSE)
    await wait_for(hass, lambda: hass.states.get(ENTITY).state == STATE_PAUSED)
    await call(hass, SERVICE_MEDIA_PLAY)
    await wait_for(hass, lambda: hass.states.get(ENTITY).state == STATE_PLAYING)
    await call(hass, SERVICE_MEDIA_NEXT_TRACK)
    await wait_for(hass, lambda: attrs(hass)["media_title"] == "Motion Sickness")
    # The station favors this one already.
    await wait_for(hass, lambda: attrs(hass)["standing"]["preference"] == 1)
    await call(hass, SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: 0.3})
    await wait_for(hass, lambda: attrs(hass)["volume_level"] == 0.3)
    await call(hass, SERVICE_MEDIA_STOP)
    await wait_for(hass, lambda: hass.states.get(ENTITY).state == STATE_IDLE)
    assert attrs(hass)["radio_state"] == "stopped"
    # Play starts the station that was on.
    await call(hass, SERVICE_MEDIA_PLAY)
    await wait_for(hass, lambda: hass.states.get(ENTITY).state == STATE_PLAYING)


async def test_stations(hass: HomeAssistant, setup) -> None:
    await setup()
    await call(hass, SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: "Deep focus"})
    await wait_for(hass, lambda: attrs(hass)["station_id"] == "stn-focus")
    assert attrs(hass)["station_mode"] == "steady"
    await call(
        hass,
        SERVICE_PLAY_MEDIA,
        {ATTR_MEDIA_CONTENT_ID: "station:stn-late", ATTR_MEDIA_CONTENT_TYPE: "station"},
    )
    await wait_for(hass, lambda: attrs(hass)["source"] == "Late night")
    with pytest.raises(ServiceValidationError):
        await call(hass, SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: "Nowhere"})
    entity = hass.data[MP_DOMAIN].get_entity(ENTITY)
    browse = await entity.async_browse_media()
    assert [child.title for child in browse.children] == [
        "Morning drift",
        "Deep focus",
        "Late night",
    ]
    assert browse.children[0].media_content_id == "station:stn-morning"


async def test_steering(hass: HomeAssistant, setup) -> None:
    await setup()
    await call(hass, "steer_track", {"choice": "favor"}, DOMAIN)
    await wait_for(hass, lambda: attrs(hass)["standing"]["preference"] == 1)
    await call(hass, "steer_track", {"choice": "rest", "rest_days": 30}, DOMAIN)
    await wait_for(hass, lambda: attrs(hass)["standing"]["rest_until_ms"] is not None)
    await call(hass, "steer_track", {"choice": "end_rest"}, DOMAIN)
    await wait_for(hass, lambda: attrs(hass)["standing"]["rest_until_ms"] is None)
    # A ban skips the track, as in the app.
    await call(hass, "steer_track", {"choice": "ban"}, DOMAIN)
    await wait_for(hass, lambda: attrs(hass)["media_title"] == "Motion Sickness")


async def test_steering_needs_the_stations_scope(hass: HomeAssistant, setup) -> None:
    await setup("control")
    assert attrs(hass)["can_steer"] is False
    with pytest.raises(ServiceValidationError):
        await call(hass, "steer_track", {"choice": "favor"}, DOMAIN)


async def test_the_radio_pushes_changes(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    await wait_for(hass, lambda: attrs(hass)["live_updates"] is True)
    radio.send("advance")
    # No poll is due for a minute; the event stream brings the change.
    await wait_for(
        hass, lambda: attrs(hass)["media_title"] == "Motion Sickness", timeout=3
    )
    radio.send("state fault native-audio-fault")
    await wait_for(hass, lambda: attrs(hass)["radio_state"] == "fault", timeout=3)
    assert attrs(hass)["health"]["fault"] == "native-audio-fault"
    radio.send("stations Focus, renamed")
    await wait_for(
        hass, lambda: "Focus, renamed" in attrs(hass)["source_list"], timeout=3
    )


async def test_an_unreachable_radio_is_unavailable(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    radio.stop()
    await async_update_entity(hass, ENTITY)
    await wait_for(hass, lambda: hass.states.get(ENTITY).state == STATE_UNAVAILABLE)


# ── Albums, playlists and collections (RL.11) ────────────────────────────


def player(hass: HomeAssistant):
    return hass.data[MP_DOMAIN].get_entity(ENTITY)


async def lists_on(hass: HomeAssistant, radio: Radio) -> None:
    """The radio becomes one that plays lists (`features: ["lists"]`, RL.3)."""
    radio.send("lists on")
    await wait_for(hass, lambda: attrs(hass)["plays_lists"] is True)


def play_list(content_id: str, content_type: str = "album") -> dict:
    return {ATTR_MEDIA_CONTENT_ID: content_id, ATTR_MEDIA_CONTENT_TYPE: content_type}


async def test_an_older_radio_offers_no_lists(hass: HomeAssistant, setup) -> None:
    await setup()
    assert attrs(hass)["plays_lists"] is False
    assert attrs(hass)["list"] is None
    assert not attrs(hass)["supported_features"] & MediaPlayerEntityFeature.SEARCH_MEDIA
    # Media opens on the stations, as before, with nothing to search.
    stations = await player(hass).async_browse_media()
    assert (stations.title, stations.can_search) == ("Stations", False)
    with pytest.raises(BrowseError):
        await player(hass).async_browse_media("albums", "albums")
    with pytest.raises(SearchError):
        await player(hass).async_search_media(SearchMediaQuery(search_query="blue"))
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, SERVICE_PLAY_MEDIA, play_list("album:al-000-blue"))
    assert err.value.translation_key == "lists_unsupported"


async def test_browses_albums_playlists_and_collections_a_page_at_a_time(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    await lists_on(hass, radio)
    root = await player(hass).async_browse_media()
    assert [child.title for child in root.children] == [
        "Stations",
        "Albums",
        "Playlists",
        "Collections",
    ]
    # Media's search box shows on a folder that says it can be searched.
    assert root.can_search and all(child.can_search for child in root.children)
    albums = await player(hass).async_browse_media("albums", "albums")
    assert albums.can_search
    # 64 albums and More: the radio has 70.
    assert len(albums.children) == 65
    first = albums.children[0]
    assert (first.title, first.media_content_id, first.media_class) == (
        "Kind of Blue · Miles Davis",
        "album:al-000-blue",
        MediaClass.ALBUM,
    )
    assert first.can_play and not first.can_expand
    more = albums.children[-1]
    assert (more.title, more.can_play, more.can_expand) == ("More albums", False, True)
    rest = await player(hass).async_browse_media(
        more.media_content_type, more.media_content_id
    )
    assert [child.title for child in rest.children] == [
        f"Record {n} · Band" for n in range(64, 70)
    ]
    playlists = await player(hass).async_browse_media("playlists", "playlists")
    assert [child.title for child in playlists.children] == ["Rainy days", "Running"]
    collections = await player(hass).async_browse_media("collections", "collections")
    assert [child.media_content_id for child in collections.children] == [
        "collection:col-rain"
    ]
    stations = await player(hass).async_browse_media("stations", "stations")
    assert len(stations.children) == 3
    # The radio's refusal, in its words.
    radio.send("collections off")
    with pytest.raises(BrowseError, match="Turn on Living Collections"):
        await player(hass).async_browse_media("collections", "collections")


async def test_searches_stations_and_the_radios_lists(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    await lists_on(hass, radio)
    assert attrs(hass)["supported_features"] & MediaPlayerEntityFeature.SEARCH_MEDIA
    found = await player(hass).async_search_media(SearchMediaQuery(search_query="rain"))
    assert [item.media_content_id for item in found.result] == [
        "playlist:pl-rain",
        "collection:col-rain",
    ]
    found = await player(hass).async_search_media(
        SearchMediaQuery(search_query="NIGHT")
    )
    assert [item.title for item in found.result] == ["Late night"]
    only = await player(hass).async_search_media(
        SearchMediaQuery(search_query="rain", media_filter_classes=[MediaClass.ALBUM])
    )
    assert only.result == []
    # Searched from inside a folder in Media: that folder's kind only.
    inside = await player(hass).async_search_media(
        SearchMediaQuery(
            search_query="r",
            media_content_type="playlists",
            media_content_id="playlists",
        )
    )
    assert [item.title for item in inside.result] == ["Rainy days", "Running"]
    # Collections switched off still leave the playlists to find.
    radio.send("collections off")
    found = await player(hass).async_search_media(SearchMediaQuery(search_query="rain"))
    assert [item.title for item in found.result] == ["Rainy days"]


async def test_plays_a_list_and_shows_it_in_place_of_the_station(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    await lists_on(hass, radio)
    await call(hass, SERVICE_PLAY_MEDIA, play_list("album:al-000-blue"))
    await wait_for(hass, lambda: attrs(hass)["list"] is not None)
    assert attrs(hass)["list"] == {
        "kind": "album",
        "id": "al-000-blue",
        "name": "Kind of Blue",
        "artist": "Miles Davis",
        "index": 0,
        "count": 3,
        "shuffled": False,
        "place": "Album · 1 of 3",
    }
    assert attrs(hass)["station_id"] is None
    # No station chose the song, so no "why" (the card shows none).
    assert attrs(hass)["selection"] is None
    assert attrs(hass)["source"] == "Kind of Blue"
    assert attrs(hass)["media_playlist"] == "Kind of Blue"
    assert attrs(hass)["supported_features"] & MediaPlayerEntityFeature.PREVIOUS_TRACK
    await call(hass, SERVICE_MEDIA_NEXT_TRACK)
    await wait_for(hass, lambda: attrs(hass)["list"]["index"] == 1)
    await call(hass, SERVICE_MEDIA_PREVIOUS_TRACK)
    await wait_for(hass, lambda: attrs(hass)["list"]["index"] == 0)
    # As an automation writes it: the kind as the type and the bare ID.
    await call(hass, SERVICE_PLAY_MEDIA, play_list("pl-rain", "playlist"))
    await wait_for(hass, lambda: attrs(hass)["list"]["name"] == "Rainy days")
    # A station takes over again, and Previous goes with the list.
    await call(hass, SERVICE_SELECT_SOURCE, {ATTR_INPUT_SOURCE: "Deep focus"})
    await wait_for(hass, lambda: attrs(hass)["list"] is None)
    assert attrs(hass)["source"] == "Deep focus"
    assert (
        not attrs(hass)["supported_features"] & MediaPlayerEntityFeature.PREVIOUS_TRACK
    )


async def test_shuffle_plays_the_next_list_shuffled(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    # An older radio offers no Shuffle.
    assert not attrs(hass)["supported_features"] & MediaPlayerEntityFeature.SHUFFLE_SET
    assert ATTR_MEDIA_SHUFFLE not in attrs(hass)
    await lists_on(hass, radio)
    assert attrs(hass)["supported_features"] & MediaPlayerEntityFeature.SHUFFLE_SET
    assert attrs(hass)[ATTR_MEDIA_SHUFFLE] is False
    await call(hass, SERVICE_SHUFFLE_SET, {ATTR_MEDIA_SHUFFLE: True})
    assert attrs(hass)[ATTR_MEDIA_SHUFFLE] is True
    await call(hass, SERVICE_PLAY_MEDIA, play_list("album:al-000-blue"))
    await wait_for(hass, lambda: (attrs(hass)["list"] or {}).get("shuffled") is True)
    # Off again: the next list plays in its own order.
    await call(hass, SERVICE_SHUFFLE_SET, {ATTR_MEDIA_SHUFFLE: False})
    await call(hass, SERVICE_PLAY_MEDIA, play_list("pl-rain", "playlist"))
    await wait_for(
        hass,
        lambda: (attrs(hass)["list"] or {}).get("name") == "Rainy days"
        and attrs(hass)["list"]["shuffled"] is False,
    )


async def test_says_why_the_radio_cant_play_a_list(
    hass: HomeAssistant, setup, radio: Radio
) -> None:
    await setup()
    await lists_on(hass, radio)
    with pytest.raises(HomeAssistantError) as err:
        await call(hass, SERVICE_PLAY_MEDIA, play_list("playlist:pl-gone", "playlist"))
    assert err.value.translation_key == "radio_refused"
    assert err.value.translation_placeholders["reason"] == (
        "The radio’s music server account can’t see this playlist. "
        "Share it with that account on your music server."
    )
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, SERVICE_PLAY_MEDIA, play_list("album:", "album"))
    assert err.value.translation_key == "unknown_list"
    assert attrs(hass)["source"] == "Morning drift"
