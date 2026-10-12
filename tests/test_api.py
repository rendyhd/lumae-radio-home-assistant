"""The client against the radio's real HTTPS boundary (radio_harness.mjs)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import aiohttp
import pytest

from custom_components.lumae_radio.api import (
    LumaeRadioClient,
    RadioAuthError,
    RadioHostRejected,
    RadioIdentityError,
    RadioScopeError,
    fetch_fingerprint,
    format_fingerprint,
    normalize_origin,
    radio_address,
    short_fingerprint,
)

from .conftest import Radio


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


def client(
    session: aiohttp.ClientSession,
    radio: Radio,
    key: str | None = "full",
    *,
    origin: str | None = None,
    connect: str | None = None,
    fingerprint: str | None = None,
) -> LumaeRadioClient:
    return LumaeRadioClient(
        session,
        radio_address(origin or radio.origin, connect),
        fingerprint or radio.fingerprint,
        radio.keys[key] if key else None,
    )


def test_origins_are_normalized() -> None:
    assert normalize_origin("lumae-radio.local") == "https://lumae-radio.local:8443"
    assert normalize_origin(" 192.168.1.50:8443 ") == "https://192.168.1.50:8443"
    assert (
        normalize_origin("https://Lumae-Radio.local:8443/")
        == "https://lumae-radio.local:8443"
    )
    assert normalize_origin("http://kitchen.local:9443") == "https://kitchen.local:9443"
    assert normalize_origin("[fe80::1]:8443") == "https://[fe80::1]:8443"
    for bad in ("", "https://x.local/api", "https://user@x.local", "ftp://x.local"):
        with pytest.raises(ValueError):
            normalize_origin(bad)


def test_an_address_names_the_radio_and_reaches_it_elsewhere() -> None:
    address = radio_address("https://lumae-radio.local:8443", "192.168.1.50")
    assert address.host_header == "lumae-radio.local:8443"
    assert address.url("/api/v1/status") == "https://192.168.1.50:8443/api/v1/status"
    assert (
        radio_address("https://[fd00::5]:8443").url("/x") == "https://[fd00::5]:8443/x"
    )


def test_identity_is_shown_as_the_app_and_doctor_show_it() -> None:
    fingerprint = "3fa107" + "0" * 54 + "529c"
    assert short_fingerprint(fingerprint) == "3F:A1:07 … 52:9C"
    assert format_fingerprint(fingerprint).startswith("3F:A1:07:00")
    assert len(format_fingerprint(fingerprint)) == 95


async def test_pins_the_certificate_it_first_sees(radio: Radio) -> None:
    assert await fetch_fingerprint("127.0.0.1", radio.port) == radio.fingerprint


async def test_reads_status_and_stations(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    radio_client = client(session, radio)
    status = await radio_client.status()
    assert status["playback"]["track"]["title"] == "Holocene"
    stations = await radio_client.stations()
    assert [station["name"] for station in stations] == [
        "Morning drift",
        "Deep focus",
        "Late night",
    ]
    reply = await radio_client.station("stn-morning")
    assert reply.revision == "3"


async def test_names_the_radio_while_reaching_its_address(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    named = client(session, radio, origin=radio.named_origin, connect="127.0.0.1")
    assert (await named.status())["stealth"] is True
    stranger = client(
        session, radio, origin=f"https://other.test:{radio.port}", connect="127.0.0.1"
    )
    with pytest.raises(RadioHostRejected):
        await stranger.status()


async def test_refuses_another_certificate(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    with pytest.raises(RadioIdentityError):
        await client(session, radio, fingerprint="0" * 64).status()


async def test_public_status_needs_no_key(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    assert await client(session, radio, None).auth_status() == {"claimed": True}


async def test_keys_and_scopes(session: aiohttp.ClientSession, radio: Radio) -> None:
    full = client(session, radio, "full")
    assert await full.has_scope("control") and await full.has_scope("stations")
    control = client(session, radio, "control")
    assert await control.has_scope("control") and not await control.has_scope(
        "stations"
    )
    read = client(session, radio, "read")
    assert not await read.has_scope("control")
    with pytest.raises(RadioScopeError):
        await client(session, radio, "admin").status()
    radio.send("revoke control")
    with pytest.raises(RadioAuthError):
        await control.status()


async def test_a_command_survives_another_client_moving_the_radio(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    radio_client = client(session, radio)
    await radio_client.status()
    radio.send("advance")  # the status revision moves on without this client
    operation_id = await radio_client.command("pause")
    assert operation_id
    finished = await radio_client.wait_operation(operation_id, timeout=5)
    assert finished and finished["status"] == "completed"
    assert (await radio_client.status())["playback"]["state"] == "paused"


async def test_feedback_reads_the_station_revisions_first(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    radio_client = client(session, radio)
    operation_id = await radio_client.feedback("stn-morning", "trk-holocene", "avoid")
    assert operation_id
    await radio_client.wait_operation(operation_id, timeout=5)
    station = (await radio_client.station("stn-morning")).data
    row = next(
        item for item in station["feedback"] if item["trackId"] == "trk-holocene"
    )
    assert row["stationPreference"] == -1
    ban = await radio_client.feedback("stn-morning", "trk-holocene", "ban")
    await radio_client.wait_operation(ban, timeout=5)
    reply = await radio_client.station("stn-morning")
    assert reply.revision == "4"
    assert reply.data["bans"][0]["trackId"] == "trk-holocene"


async def test_artwork_is_an_image(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    body, content_type = await client(session, radio).artwork("trk-holocene")
    assert content_type == "image/png"
    assert body.startswith(b"\x89PNG")


async def test_events_arrive_as_the_radio_changes(
    session: aiohttp.ClientSession, radio: Radio
) -> None:
    events = client(session, radio).events()
    assert (await anext(events))["type"] == "connected"
    radio.send("advance")
    event = await asyncio.wait_for(anext(events), 5)
    assert event["type"] == "status"
    await events.aclose()
