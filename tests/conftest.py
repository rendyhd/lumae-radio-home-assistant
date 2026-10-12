"""Fixtures: a radio from radio_harness.mjs (the radio's real HTTPS code), and Home Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lumae_radio.const import (
    CONF_API_KEY,
    CONF_CONNECT_HOST,
    CONF_FINGERPRINT,
    CONF_ORIGIN,
    DOMAIN,
)

HERE = Path(__file__).parent
HARNESS = HERE / "radio_harness.mjs"
RADIO_SERVER = HERE.parent.parent / "headless" / "service" / "http-server.mjs"


@dataclass
class Radio:
    """A running test radio."""

    process: subprocess.Popen[str]
    port: int
    origins: list[str]
    fingerprint: str
    keys: dict[str, str]

    @property
    def origin(self) -> str:
        """`https://127.0.0.1:<port>`: reached by its own address."""
        return self.origins[0]

    @property
    def named_origin(self) -> str:
        """`https://radio.test:<port>`: a name reached through 127.0.0.1, as after discovery."""
        return self.origins[1]

    def send(self, line: str) -> None:
        """Change the radio from outside, as another client or the radio itself would."""
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(f"{line}\n")
        self.process.stdin.flush()
        assert self.process.stdout.readline().strip() == "ok"

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(10)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components/."""


@pytest.fixture
def radio(socket_enabled: None) -> Generator[Radio]:
    """A radio on 127.0.0.1 that also answers to `radio.test`."""
    if not RADIO_SERVER.exists() or shutil.which("node") is None:
        pytest.skip("needs the Lumae source's headless/ and Node 24")
    process = subprocess.Popen(
        [
            "node",
            "--no-warnings",
            str(HARNESS),
            "--origins",
            "https://127.0.0.1:{port},https://radio.test:{port}",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        raise RuntimeError(
            f"radio harness did not start: {process.stderr.read() if process.stderr else ''}"
        )
    info = json.loads(line)
    test_radio = Radio(
        process=process,
        port=info["port"],
        origins=info["origins"],
        fingerprint=info["fingerprint"],
        keys=info["keys"],
    )
    yield test_radio
    test_radio.stop()


@pytest.fixture(autouse=True)
def frontend(hass: HomeAssistant) -> Generator[MagicMock]:
    """Stand in for the frontend and HTTP server, which the test install doesn't carry."""
    hass.config.components.update({"frontend", "http"})
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch("custom_components.lumae_radio.add_extra_js_url") as add_extra_js_url:
        yield add_extra_js_url


@pytest.fixture
def make_entry(hass: HomeAssistant, radio: Radio) -> Callable[..., MockConfigEntry]:
    def make(key: str = "full", named: bool = False) -> MockConfigEntry:
        data = {
            CONF_ORIGIN: radio.named_origin if named else radio.origin,
            CONF_FINGERPRINT: radio.fingerprint,
            CONF_API_KEY: radio.keys[key],
        }
        if named:
            data[CONF_CONNECT_HOST] = "127.0.0.1"
        entry = MockConfigEntry(
            domain=DOMAIN, title="Lumae Radio", unique_id=radio.fingerprint, data=data
        )
        entry.add_to_hass(hass)
        return entry

    return make


async def wait_for(
    hass: HomeAssistant, check: Callable[[], bool], timeout: float = 6
) -> None:
    """Until `check` holds: the radio applies commands and pushes events a moment later."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        await hass.async_block_till_done()
        if check():
            return
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for the radio")
        await asyncio.sleep(0.05)
