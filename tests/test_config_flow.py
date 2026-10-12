"""Adding a radio: typed in, discovered, a new key, a new address."""

from __future__ import annotations

from ipaddress import ip_address

from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from custom_components.lumae_radio.config_flow import radio_title
from custom_components.lumae_radio.const import (
    CONF_API_KEY,
    CONF_CONNECT_HOST,
    CONF_FINGERPRINT,
    CONF_ORIGIN,
    DOMAIN,
)

from .conftest import Radio


def discovery(
    radio: Radio, origin: str | None = None, version: str = "1"
) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname="lumae-radio.local.",
        name="Lumae Radio._lumae-radio._tcp.local.",
        port=radio.port,
        type="_lumae-radio._tcp.local.",
        properties={"v": version, "origin": origin or radio.named_origin},
    )


def test_titles_come_from_the_radio_name() -> None:
    assert radio_title("https://lumae-radio.local:8443") == "Lumae Radio"
    assert radio_title("https://kitchen.local:8443") == "Kitchen Radio"
    assert radio_title("https://192.168.1.50:8443") == "Lumae Radio"


async def test_typed_address(hass: HomeAssistant, radio: Radio, frontend) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": f"127.0.0.1:{radio.port}"}
    )
    assert result["step_id"] == "api_key"
    assert result["description_placeholders"]["web_address"] == radio.origin
    assert " … " in result["description_placeholders"]["identity"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "not a key"}
    )
    assert result["errors"] == {"base": "invalid_api_key"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: radio.keys["read"]}
    )
    assert result["errors"] == {"base": "missing_control"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: radio.keys["admin"]}
    )
    assert result["errors"] == {"base": "missing_read"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: radio.keys["full"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Lumae Radio"
    assert result["result"].unique_id == radio.fingerprint
    assert result["data"] == {
        CONF_ORIGIN: radio.origin,
        CONF_FINGERPRINT: radio.fingerprint,
        CONF_API_KEY: radio.keys["full"],
    }
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_an_address_the_radio_does_not_answer_to(
    hass: HomeAssistant, radio: Radio
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": "https://127.0.0.1:1/api"}
    )
    assert result["errors"] == {"address": "invalid_address"}
    radio.stop()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"address": f"127.0.0.1:{radio.port}"}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_discovered(hass: HomeAssistant, radio: Radio, frontend) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery(radio)
    )
    assert result["step_id"] == "api_key"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: radio.keys["control"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ORIGIN] == radio.named_origin
    assert result["data"][CONF_CONNECT_HOST] == "127.0.0.1"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)


async def test_discovery_follows_a_known_radio(
    hass: HomeAssistant, radio: Radio, make_entry
) -> None:
    entry = make_entry()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery(radio)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_ORIGIN] == radio.named_origin
    assert entry.data[CONF_CONNECT_HOST] == "127.0.0.1"


async def test_discovery_of_something_else(hass: HomeAssistant, radio: Radio) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=discovery(radio, version="2")
    )
    assert result["reason"] == "not_lumae_radio"


async def test_discovery_of_a_name_the_radio_does_not_answer_to(
    hass: HomeAssistant, radio: Radio
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_ZEROCONF},
        data=discovery(radio, origin=f"https://other.test:{radio.port}"),
    )
    assert result["reason"] == "host_rejected"


async def test_a_revoked_key_asks_for_a_new_one(
    hass: HomeAssistant, radio: Radio, make_entry, frontend
) -> None:
    entry = make_entry("control")
    radio.send("revoke control")
    assert not await hass.config_entries.async_setup(entry.entry_id)
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]

    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_API_KEY: radio.keys["control"]}
    )
    assert result["errors"] == {"base": "invalid_api_key"}
    result = await hass.config_entries.flow.async_configure(
        flows[0]["flow_id"], {CONF_API_KEY: radio.keys["full"]}
    )
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == radio.keys["full"]
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_keeps_the_same_radio(
    hass: HomeAssistant, radio: Radio, make_entry, frontend
) -> None:
    entry = make_entry(named=True)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"address": radio.origin, CONF_API_KEY: radio.keys["control"]},
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_ORIGIN] == radio.origin
    assert entry.data[CONF_CONNECT_HOST] is None
    assert entry.data[CONF_API_KEY] == radio.keys["control"]
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(entry.entry_id)
