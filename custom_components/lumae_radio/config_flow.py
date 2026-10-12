"""Adding a Lumae Radio: find it, pin its identity, and take an API key.

A radio announces itself as `_lumae-radio._tcp` with TXT `v=1` and `origin=` its web address
(headless/docs/USAGE.md). Home Assistant pins the radio's certificate the first time it
connects, as the Lumae app does, and shows the identity so it can be compared with the app's
Access page or `lumae-radio.mjs doctor`.
"""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .api import (
    API_KEY_PATTERN,
    LumaeRadioClient,
    RadioAddress,
    RadioAuthError,
    RadioError,
    RadioHostRejected,
    RadioIdentityError,
    RadioScopeError,
    fetch_fingerprint,
    format_fingerprint,
    is_ip_address,
    normalize_origin,
    radio_address,
    short_fingerprint,
)
from .const import (
    CONF_API_KEY,
    CONF_CONNECT_HOST,
    CONF_FINGERPRINT,
    CONF_ORIGIN,
    DOMAIN,
    LOGGER,
    SCOPE_CONTROL,
)

CONF_ADDRESS = "address"

KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def radio_title(origin: str) -> str:
    """`https://lumae-radio.local:8443` → "Lumae Radio"; `kitchen.local` → "Kitchen Radio"."""
    hostname = urlsplit(origin).hostname or ""
    if not hostname or is_ip_address(hostname):
        return "Lumae Radio"
    words = hostname.split(".")[0].replace("-", " ").replace("_", " ").title()
    return words if "radio" in words.lower() else f"{words} Radio"


def _discovered_host(info: ZeroconfServiceInfo) -> str:
    """An IPv4 address when the radio has one; a bare link-local IPv6 can't be dialed."""
    addresses = [address for address in info.ip_addresses if address.version == 4]
    return str(addresses[0]) if addresses else str(info.ip_address)


class LumaeRadioConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a Lumae Radio."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: RadioAddress | None = None
        self._fingerprint: str | None = None

    async def _identify(self, address: RadioAddress) -> str | None:
        """Pin the radio's certificate and check it has an owner; an error key, or None."""
        try:
            fingerprint = await fetch_fingerprint(address.connect_host, address.port)
            client = LumaeRadioClient(
                async_get_clientsession(self.hass), address, fingerprint, None
            )
            status = await client.auth_status()
        except RadioHostRejected:
            return "host_rejected"
        except RadioError as err:
            LOGGER.debug(
                "Lumae Radio at %s did not answer: %s", address.origin, err.code
            )
            return "cannot_connect"
        if status.get("claimed") is not True:
            return "not_adopted"
        self._address = address
        self._fingerprint = fingerprint
        return None

    async def _check_key(self, api_key: str) -> str | None:
        """Whether the key reads and controls this radio; an error key, or None."""
        if not API_KEY_PATTERN.match(api_key):
            return "invalid_api_key"
        assert self._address is not None and self._fingerprint is not None
        client = LumaeRadioClient(
            async_get_clientsession(self.hass),
            self._address,
            self._fingerprint,
            api_key,
        )
        try:
            await client.status()
            if not await client.has_scope(SCOPE_CONTROL):
                return "missing_control"
        except RadioAuthError:
            return "invalid_api_key"
        except RadioScopeError:
            return "missing_read"
        except RadioIdentityError:
            return "identity_changed"
        except RadioError:
            return "cannot_connect"
        return None

    def _placeholders(self) -> dict[str, str]:
        assert self._address is not None and self._fingerprint is not None
        return {
            "name": radio_title(self._address.origin),
            "web_address": self._address.origin,
            "identity": short_fingerprint(self._fingerprint),
            "fingerprint": format_fingerprint(self._fingerprint),
        }

    def _entry_data(self, api_key: str) -> dict[str, Any]:
        assert self._address is not None and self._fingerprint is not None
        data: dict[str, Any] = {
            CONF_ORIGIN: self._address.origin,
            CONF_FINGERPRINT: self._fingerprint,
            CONF_API_KEY: api_key,
        }
        if self._address.connect_host != self._address.hostname:
            data[CONF_CONNECT_HOST] = self._address.connect_host
        return data

    # ── Typed in ─────────────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                address = radio_address(user_input[CONF_ADDRESS])
            except ValueError:
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                if error := await self._identify(address):
                    errors["base"] = error
                else:
                    await self.async_set_unique_id(self._fingerprint)
                    self._abort_if_unique_id_configured()
                    return await self.async_step_api_key()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_ADDRESS): str}), user_input
            ),
            errors=errors,
        )

    # ── Found on the network ─────────────────────────────────────────────

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        properties = discovery_info.properties
        if properties.get("v") != "1" or not properties.get("origin"):
            return self.async_abort(reason="not_lumae_radio")
        try:
            origin = normalize_origin(properties["origin"])
        except ValueError:
            return self.async_abort(reason="not_lumae_radio")
        host = _discovered_host(discovery_info)
        if ip_address(host).is_link_local and ip_address(host).version == 6:
            return self.async_abort(reason="cannot_connect")
        address = radio_address(origin, host)
        if error := await self._identify(address):
            return self.async_abort(reason=error)
        await self.async_set_unique_id(self._fingerprint)
        # A radio that moved to a new address keeps its entry; Home Assistant follows it.
        self._abort_if_unique_id_configured(
            updates={CONF_ORIGIN: address.origin, CONF_CONNECT_HOST: host}
        )
        self.context["title_placeholders"] = {"name": radio_title(origin)}
        return await self.async_step_api_key()

    # ── The API key ──────────────────────────────────────────────────────

    async def async_step_api_key(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if error := await self._check_key(api_key):
                errors["base"] = error
            else:
                assert self._address is not None
                return self.async_create_entry(
                    title=radio_title(self._address.origin),
                    data=self._entry_data(api_key),
                )
        return self.async_show_form(
            step_id="api_key",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): KEY_SELECTOR}),
            description_placeholders=self._placeholders(),
            errors=errors,
        )

    # ── A revoked or expired key ─────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._address = radio_address(
            entry_data[CONF_ORIGIN], entry_data.get(CONF_CONNECT_HOST)
        )
        self._fingerprint = entry_data[CONF_FINGERPRINT]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if error := await self._check_key(api_key):
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): KEY_SELECTOR}),
            description_placeholders=self._placeholders(),
            errors=errors,
        )

    # ── A new address or key ─────────────────────────────────────────────

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                address = radio_address(user_input[CONF_ADDRESS])
            except ValueError:
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                if error := await self._identify(address):
                    errors["base"] = error
                else:
                    await self.async_set_unique_id(self._fingerprint)
                    # Another certificate is another radio (or this one set up again).
                    self._abort_if_unique_id_mismatch(reason="wrong_radio")
                    api_key = user_input[CONF_API_KEY].strip()
                    if error := await self._check_key(api_key):
                        errors["base"] = error
                    else:
                        data = self._entry_data(api_key)
                        if CONF_CONNECT_HOST not in data:
                            data[CONF_CONNECT_HOST] = None
                        return self.async_update_reload_and_abort(
                            entry, data_updates=data
                        )
        suggested = user_input or {
            CONF_ADDRESS: entry.data[CONF_ORIGIN],
            CONF_API_KEY: entry.data[CONF_API_KEY],
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_ADDRESS): str,
                        vol.Required(CONF_API_KEY): KEY_SELECTOR,
                    }
                ),
                suggested,
            ),
            errors=errors,
        )
