"""Keeps one radio's status and stations current.

The radio pushes an event whenever its status, stations or libraries change, so Home Assistant
re-reads at once. A slow poll stays on as a backstop, and polls faster while the event stream
is down.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import model
from .api import (
    LumaeRadioClient,
    RadioAuthError,
    RadioConnectionError,
    RadioError,
    RadioIdentityError,
    RadioScopeError,
)
from .const import DOMAIN, LOGGER, SCOPE_STATIONS

POLL_WITH_EVENTS = timedelta(seconds=60)
POLL_WITHOUT_EVENTS = timedelta(seconds=10)
STATIONS_MAX_AGE_SECONDS = 3600
EVENTS_RETRY_MAX_SECONDS = 60
# How long a playback action waits for the radio to apply it before Home Assistant moves on.
COMMAND_WAIT_SECONDS = 4
FEEDBACK_WAIT_SECONDS = 20

type LumaeRadioConfigEntry = ConfigEntry[LumaeRadioCoordinator]


@dataclass(frozen=True)
class RadioData:
    """One read of the radio: its status, when it was read, and its stations."""

    status: dict[str, Any]
    read_at: datetime
    stations: list[dict[str, Any]]


class LumaeRadioCoordinator(DataUpdateCoordinator[RadioData]):
    """One radio."""

    config_entry: LumaeRadioConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: LumaeRadioConfigEntry,
        client: LumaeRadioClient,
        scopes: frozenset[str],
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=POLL_WITHOUT_EVENTS,
            # Events come in bursts (a command accepted, then applied): read at once, then
            # again shortly after, never ten seconds late.
            request_refresh_debouncer=Debouncer(
                hass, LOGGER, cooldown=0.25, immediate=True
            ),
        )
        self.client = client
        self.scopes = scopes
        self.events_connected = False
        self._stations: list[dict[str, Any]] | None = None
        self._stations_due = True
        self._stations_read_at = 0.0
        self._playing_key: tuple[str | None, str | None] | None = None

    async def _async_update_data(self) -> RadioData:
        try:
            status = await self.client.status()
            stations = await self._current_stations(status)
        except RadioAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="api_key_rejected"
            ) from err
        except RadioIdentityError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="identity_changed"
            ) from err
        except RadioError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="radio_unreachable"
            ) from err
        return RadioData(status=status, read_at=dt_util.utcnow(), stations=stations)

    async def _current_stations(self, status: dict[str, Any]) -> list[dict[str, Any]]:
        """The station list, read whole when it changed and per station when the track did.

        The playing station is read again at each track or station change, so the track's
        standing (favored, resting, banned) is current without reading every station.
        """
        stale = time.monotonic() - self._stations_read_at > STATIONS_MAX_AGE_SECONDS
        if self._stations is None or self._stations_due or stale:
            self._stations_due = False
            try:
                self._stations = await self.client.stations()
            except RadioError:
                self._stations_due = True
                raise
            self._stations_read_at = time.monotonic()
            self._playing_key = None
        station_id = model.station_id(status)
        track = model.track(status)
        key = (station_id, track["id"] if track else None)
        if station_id is not None and key != self._playing_key:
            try:
                fresh = (await self.client.station(station_id)).data
            except RadioError as err:
                if err.code != "station-not-found" or err.status != 404:
                    raise
            else:
                self._stations = [
                    fresh if station.get("id") == station_id else station
                    for station in self._stations
                ]
                if model.find_station(self._stations, station_id) is None:
                    self._stations.append(fresh)
            self._playing_key = key
        return list(self._stations)

    # ── Live updates ─────────────────────────────────────────────────────

    @callback
    def start_events(self) -> None:
        self.config_entry.async_create_background_task(
            self.hass,
            self._listen(),
            f"{DOMAIN} events {self.config_entry.entry_id}",
        )

    async def _listen(self) -> None:
        delay = 1
        while True:
            try:
                async for event in self.client.events():
                    kind = event.get("type")
                    if kind == "connected":
                        delay = 1
                        self._events_up(True)
                        await self.async_request_refresh()
                    elif kind in ("stations", "libraries"):
                        self._stations_due = True
                        await self.async_request_refresh()
                    elif kind == "status":
                        await self.async_request_refresh()
            except RadioAuthError:
                # The poll reports it and starts the reauthentication flow.
                delay = EVENTS_RETRY_MAX_SECONDS
            except RadioError as err:
                LOGGER.debug("Lumae Radio event stream ended: %s", err.code)
            self._events_up(False)
            await asyncio.sleep(delay)
            delay = min(delay * 2, EVENTS_RETRY_MAX_SECONDS)

    @callback
    def _events_up(self, connected: bool) -> None:
        self.events_connected = connected
        self.update_interval = POLL_WITH_EVENTS if connected else POLL_WITHOUT_EVENTS

    # ── Actions ──────────────────────────────────────────────────────────

    async def async_command(self, action: str, **payload: Any) -> None:
        """Send a playback command and wait briefly for the radio to apply it."""
        try:
            operation_id = await self.client.command(action, **payload)
            if operation_id and action != "volume":
                finished = await self.client.wait_operation(
                    operation_id, timeout=COMMAND_WAIT_SECONDS
                )
                self._raise_if_failed(finished)
        except RadioError as err:
            raise self._action_error(err) from err
        finally:
            await self.async_request_refresh()

    async def async_steer(
        self,
        choice: str,
        *,
        rest_days: float | None = None,
        rest_until: datetime | None = None,
    ) -> None:
        """Favor, play less, clear, rest, end a rest, ban or allow the playing track."""
        if SCOPE_STATIONS not in self.scopes:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="steer_needs_stations_scope"
            )
        status = self.data.status
        track = model.track(status)
        station_id = model.station_id(status)
        if track is None or station_id is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_steer"
            )
        action = model.STEER_ACTIONS[choice]
        until = (
            model.rest_until_ms(
                int(time.time() * 1000),
                rest_days,
                int(dt_util.as_timestamp(rest_until) * 1000) if rest_until else None,
            )
            if action == "rest"
            else None
        )
        occurrence = model.playback(status).get("currentOccurrenceId")
        try:
            operation_id = await self.client.feedback(
                station_id, track["id"], action, until
            )
            if operation_id:
                self._raise_if_failed(
                    await self.client.wait_operation(
                        operation_id, timeout=FEEDBACK_WAIT_SECONDS
                    )
                )
            if action == "ban" and occurrence is not None:
                # A ban skips now, as in the Lumae app: the radio replans, and this makes sure
                # the banned track moves on.
                fresh = await self.client.status()
                if model.playback(fresh).get("currentOccurrenceId") == occurrence:
                    await self.client.command("skip")
        except RadioError as err:
            raise self._action_error(err) from err
        finally:
            self._playing_key = None
            await self.async_request_refresh()

    @staticmethod
    def _raise_if_failed(operation: dict[str, Any] | None) -> None:
        if not operation or operation.get("status") not in ("failed", "cancelled"):
            return
        code = operation.get("message")
        # A press replaced by a later one (two quick taps) is not a problem.
        if code == "newer-intent":
            return
        raise RadioError(code if isinstance(code, str) else "operation-failed")

    def _action_error(self, err: RadioError) -> HomeAssistantError:
        if isinstance(err, RadioScopeError):
            return ServiceValidationError(
                translation_domain=DOMAIN, translation_key="api_key_lacks_scope"
            )
        if isinstance(err, RadioAuthError):
            self.config_entry.async_start_reauth(self.hass)
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="api_key_rejected"
            )
        if isinstance(err, RadioIdentityError):
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="identity_changed"
            )
        if isinstance(err, RadioConnectionError):
            return HomeAssistantError(
                translation_domain=DOMAIN, translation_key="radio_unreachable"
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="radio_refused",
            translation_placeholders={"reason": model.refusal_text(err.code)},
        )
