"""Lumae Radio for Home Assistant: control a radio and show what it plays.

The integration also serves its dashboard card (`custom:lumae-radio-card`), so installing it
from HACS is all a dashboard needs.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import (
    LumaeRadioClient,
    RadioAuthError,
    RadioError,
    RadioHostRejected,
    RadioIdentityError,
    radio_address,
)
from .const import (
    CARD_FILE,
    CONF_API_KEY,
    CONF_CONNECT_HOST,
    CONF_FINGERPRINT,
    CONF_ORIGIN,
    DOMAIN,
    FRONTEND_URL,
    SCOPE_CONTROL,
    SCOPE_STATIONS,
)
from .coordinator import LumaeRadioConfigEntry, LumaeRadioCoordinator

PLATFORMS = [Platform.MEDIA_PLAYER]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the card and load it on every dashboard."""
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL,
                str(Path(__file__).parent / "frontend"),
                cache_headers=False,
            )
        ]
    )
    # The version in the address makes browsers fetch the card again after an update.
    add_extra_js_url(hass, f"{FRONTEND_URL}/{CARD_FILE}?v={integration.version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LumaeRadioConfigEntry) -> bool:
    client = LumaeRadioClient(
        async_get_clientsession(hass),
        radio_address(entry.data[CONF_ORIGIN], entry.data.get(CONF_CONNECT_HOST)),
        entry.data[CONF_FINGERPRINT],
        entry.data[CONF_API_KEY],
    )
    granted: set[str] = set()
    try:
        for scope in (SCOPE_CONTROL, SCOPE_STATIONS):
            if await client.has_scope(scope):
                granted.add(scope)
    except RadioAuthError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="api_key_rejected"
        ) from err
    except RadioIdentityError as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="identity_changed"
        ) from err
    except RadioHostRejected as err:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="host_rejected"
        ) from err
    except RadioError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="radio_unreachable"
        ) from err
    scopes = frozenset(granted)
    if SCOPE_CONTROL not in scopes:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="api_key_lacks_control"
        )

    coordinator = LumaeRadioCoordinator(hass, entry, client, scopes)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    coordinator.start_events()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LumaeRadioConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
