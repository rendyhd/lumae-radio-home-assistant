"""The radio as a media player, against the radio's real HTTPS boundary."""

from __future__ import annotations

from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_CONTENT_ID,
    ATTR_MEDIA_CONTENT_TYPE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MP_DOMAIN,
    SERVICE_PLAY_MEDIA,
    SERVICE_SELECT_SOURCE,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_MEDIA_STOP,
    SERVICE_VOLUME_SET,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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
