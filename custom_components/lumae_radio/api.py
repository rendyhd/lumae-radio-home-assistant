"""A client for one Lumae Radio's HTTPS API (headless/docs/API.md).

The radio speaks HTTPS only, with a self-signed certificate made when it was set up. Like the
Lumae app, this client pins that certificate's SHA-256 fingerprint instead of trusting a CA.
The radio also answers only requests whose Host header is exactly one of its own origins, so
the client connects to an address (which may be an IP) while naming the radio's origin.

Home Assistant signs in with a scoped API key (`Authorization: Bearer lrk.…`), never with the
owner password. Every mutation sends an `If-Match` revision and an `Idempotency-Key`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import contextlib
from dataclasses import dataclass
import hashlib
from ipaddress import ip_address
import json
import re
import secrets
import ssl
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp

DEFAULT_PORT = 8443
REQUEST_TIMEOUT = 10
# The radio's own heartbeat comes every second; this much silence means the stream is gone.
EVENTS_READ_TIMEOUT = 45
OPERATION_POLL_SECONDS = 1.0

API_KEY_PATTERN = re.compile(r"^lrk\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$")
FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ARTWORK_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
OPERATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

FEEDBACK_ACTIONS = frozenset(
    {"ban", "unban", "favour", "avoid", "neutral", "rest", "unrest"}
)
COMMANDS = frozenset({"play", "pause", "resume", "stop", "skip", "volume"})
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_IMAGE_BYTES = 4 * 1024 * 1024


class RadioError(Exception):
    """The radio refused a request or answered with a fixed error code."""

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class RadioConnectionError(RadioError):
    """The radio could not be reached, or the connection broke."""


class RadioAuthError(RadioError):
    """The API key is wrong, expired or revoked (401)."""


class RadioScopeError(RadioError):
    """The API key lacks a scope this request needs (403 insufficient-scope)."""


class RadioIdentityError(RadioError):
    """The radio's certificate is not the one pinned when it was added."""


class RadioHostRejected(RadioError):
    """The radio does not answer to this name (421 host-rejected)."""


class RadioStaleError(RadioError):
    """A revision moved since it was read (412); carries the radio's current one."""

    def __init__(self, code: str, current_revision: str | None) -> None:
        super().__init__(code, 412)
        self.current_revision = current_revision


@dataclass(frozen=True)
class RadioAddress:
    """Where the radio is: its origin (for the Host header) and the host to connect to."""

    origin: str
    hostname: str
    port: int
    connect_host: str

    @property
    def host_header(self) -> str:
        name = f"[{self.hostname}]" if ":" in self.hostname else self.hostname
        return name if self.port == 443 else f"{name}:{self.port}"

    def url(self, path: str) -> str:
        host = (
            f"[{self.connect_host}]" if ":" in self.connect_host else self.connect_host
        )
        return f"https://{host}:{self.port}{path}"


def normalize_origin(text: str) -> str:
    """`lumae-radio.local`, `192.168.1.50:8443` or a full web address → `https://host:port`."""
    value = text.strip()
    if not value:
        raise ValueError("empty")
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ValueError("not-a-web-address")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("not-a-web-address")
    if parts.path not in ("", "/"):
        raise ValueError("not-a-web-address")
    hostname = parts.hostname.lower().rstrip(".")
    try:
        port = parts.port or DEFAULT_PORT
    except ValueError as err:
        raise ValueError("not-a-web-address") from err
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{host}" if port == 443 else f"https://{host}:{port}"


def radio_address(origin: str, connect_host: str | None = None) -> RadioAddress:
    """The address for an origin, optionally reached through another host (an IP)."""
    parts = urlsplit(normalize_origin(origin))
    hostname = parts.hostname or ""
    port = parts.port or 443
    return RadioAddress(
        origin=normalize_origin(origin),
        hostname=hostname,
        port=port,
        connect_host=connect_host or hostname,
    )


def is_ip_address(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def format_fingerprint(fingerprint: str) -> str:
    """Lower-case hex → `AB:CD:…`, the form `lumae-radio.mjs doctor` prints."""
    return ":".join(
        fingerprint[index : index + 2] for index in range(0, len(fingerprint), 2)
    ).upper()


def short_fingerprint(fingerprint: str) -> str:
    """`3F:A1:07 … 52:9C`, as the Lumae app shows a radio's identity under Access."""
    hexed = fingerprint.upper()

    def pairs(text: str) -> str:
        return ":".join(text[index : index + 2] for index in range(0, len(text), 2))

    return f"{pairs(hexed[:6])} … {pairs(hexed[-4:])}"


def _new_key() -> str:
    return secrets.token_urlsafe(24)


def _no_verify_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


async def fetch_fingerprint(
    host: str, port: int, timeout: float = REQUEST_TIMEOUT
) -> str:
    """The SHA-256 of the radio's certificate, read once to pin it (trust on first use)."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=_no_verify_context()),
            timeout,
        )
    except (OSError, TimeoutError, ssl.SSLError) as err:
        raise RadioConnectionError("unreachable") from err
    try:
        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object else None
        if not der:
            raise RadioConnectionError("no-certificate")
        return hashlib.sha256(der).hexdigest()
    finally:
        writer.close()
        with contextlib.suppress(OSError, ssl.SSLError):
            await writer.wait_closed()


@dataclass(frozen=True)
class Reply:
    data: Any
    revision: str | None


class LumaeRadioClient:
    """One radio, one API key, one pinned certificate."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        address: RadioAddress,
        fingerprint: str,
        api_key: str | None,
    ) -> None:
        """A client; without an API key it reads only the public `auth/status`."""
        if not FINGERPRINT_PATTERN.match(fingerprint):
            raise ValueError("invalid fingerprint")
        self._session = session
        self.address = address
        self.fingerprint = fingerprint
        self._api_key = api_key
        self._pin = aiohttp.Fingerprint(bytes.fromhex(fingerprint))
        self._status_revision: str | None = None

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        headers = {"Host": self.address.host_header, "Accept": accept}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        if_match: str | None = None,
        idempotency_key: str | None = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> Reply:
        headers = self._headers()
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        if if_match is not None:
            headers["If-Match"] = f'"{if_match}"'
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with self._session.request(
                method,
                self.address.url(path),
                headers=headers,
                data=data,
                ssl=self._pin,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                text = await response.text(encoding="utf-8")
                payload = json.loads(text) if text else None
                if response.status >= 400:
                    raise _error(response.status, payload)
                return Reply(payload, _revision(response.headers.get("ETag")))
        except aiohttp.ServerFingerprintMismatch as err:
            raise RadioIdentityError("identity-changed") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise RadioConnectionError("unreachable") from err
        except (json.JSONDecodeError, UnicodeDecodeError) as err:
            raise RadioError("unexpected-response") from err

    async def _mutate(
        self, path: str, body: dict[str, Any], revision: str, key: str
    ) -> Reply:
        """A mutation, sent again once with the same key if the connection broke.

        The radio keeps a durable receipt per key and revision, so a repeat of a request it
        did accept replays that answer instead of acting twice.
        """
        try:
            return await self._request(
                "POST", path, body=body, if_match=revision, idempotency_key=key
            )
        except RadioConnectionError:
            return await self._request(
                "POST", path, body=body, if_match=revision, idempotency_key=key
            )

    # ── Reads ────────────────────────────────────────────────────────────

    async def auth_status(self) -> dict[str, Any]:
        """Public: whether the radio has an owner yet (`{claimed}`)."""
        reply = await self._request("GET", "/api/v1/auth/status")
        return reply.data if isinstance(reply.data, dict) else {}

    async def status(self) -> dict[str, Any]:
        reply = await self._request("GET", "/api/v1/status")
        if not isinstance(reply.data, dict):
            raise RadioError("unexpected-response")
        if reply.revision is not None:
            self._status_revision = reply.revision
        return reply.data

    async def stations(self) -> list[dict[str, Any]]:
        reply = await self._request("GET", "/api/v1/stations")
        stations = reply.data.get("stations") if isinstance(reply.data, dict) else None
        if not isinstance(stations, list):
            raise RadioError("unexpected-response")
        return [station for station in stations if isinstance(station, dict)]

    async def station(self, station_id: str) -> Reply:
        if not STATION_ID_PATTERN.match(station_id):
            raise RadioError("station-not-found")
        reply = await self._request("GET", f"/api/v1/stations/{quote(station_id)}")
        if not isinstance(reply.data, dict) or reply.revision is None:
            raise RadioError("unexpected-response")
        return reply

    async def operation(self, operation_id: str) -> dict[str, Any]:
        if not OPERATION_ID_PATTERN.match(operation_id):
            raise RadioError("operation-not-found")
        reply = await self._request("GET", f"/api/v1/operations/{quote(operation_id)}")
        return reply.data if isinstance(reply.data, dict) else {}

    async def artwork(self, artwork_id: str) -> tuple[bytes, str]:
        """A cover's bytes and type; the radio serves only JPEG, PNG and WebP up to 4 MiB."""
        if not ARTWORK_ID_PATTERN.match(artwork_id):
            raise RadioError("artwork-unavailable")
        try:
            async with self._session.get(
                self.address.url(f"/api/v1/artwork/{quote(artwork_id)}"),
                headers=self._headers("image/*"),
                ssl=self._pin,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise _error(response.status, json.loads(text) if text else None)
                content_type = response.content_type
                if content_type not in IMAGE_TYPES:
                    raise RadioError("invalid-artwork")
                body = await response.content.read(MAX_IMAGE_BYTES + 1)
                if len(body) > MAX_IMAGE_BYTES:
                    raise RadioError("invalid-artwork")
                return body, content_type
        except aiohttp.ServerFingerprintMismatch as err:
            raise RadioIdentityError("identity-changed") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise RadioConnectionError("unreachable") from err
        except json.JSONDecodeError as err:
            raise RadioError("unexpected-response") from err

    async def has_scope(self, scope: str) -> bool:
        """Whether the key holds `control` or `stations`, without changing anything.

        The radio checks a key's scope before it asks for `If-Match`, so a mutation sent
        without one answers 403 for a missing scope and 428 otherwise; nothing runs.
        """
        path = {
            "control": "/api/v1/commands",
            "stations": "/api/v1/stations/lumae-scope-probe/feedback",
        }[scope]
        try:
            await self._request("POST", path, body={})
        except RadioScopeError:
            return False
        except RadioError as err:
            if err.status == 428:
                return True
            raise
        return True

    # ── Playback ─────────────────────────────────────────────────────────

    async def command(self, action: str, **payload: Any) -> str | None:
        """Play, pause, resume, stop, skip or set the volume. Returns the operation ID."""
        if action not in COMMANDS:
            raise RadioError("invalid-command")
        body = {"action": action, **payload}
        revision = self._status_revision
        if revision is None:
            await self.status()
            revision = self._status_revision
        if revision is None:
            raise RadioError("unexpected-response")
        try:
            reply = await self._mutate("/api/v1/commands", body, revision, _new_key())
        except RadioStaleError as err:
            # Another client moved the radio on; the choice made here still stands.
            fresh = err.current_revision
            if fresh is None:
                await self.status()
                fresh = self._status_revision
            reply = await self._mutate(
                "/api/v1/commands", body, fresh or revision, _new_key()
            )
        if reply.revision is not None:
            self._status_revision = reply.revision
        return _operation_id(reply.data)

    # ── Steering a track on a station ────────────────────────────────────

    async def feedback(
        self,
        station_id: str,
        track_id: str,
        action: str,
        rest_until_ms: int | None = None,
    ) -> str | None:
        """Favour, avoid, clear, rest, end a rest, ban or allow one track on a station.

        Reads the station first for its revision and feedback revision, and once more if either
        moved meanwhile, as the Lumae app does. Returns the operation ID.
        """
        if action not in FEEDBACK_ACTIONS:
            raise RadioError("invalid-feedback")
        if action == "rest" and rest_until_ms is None:
            raise RadioError("invalid-feedback")
        path = f"/api/v1/stations/{quote(station_id)}/feedback"

        async def send() -> Reply:
            station = await self.station(station_id)
            body: dict[str, Any] = {"trackId": track_id, "action": action}
            if action not in ("ban", "unban"):
                body["feedbackRevision"] = station.data.get("feedbackRevision", 0)
            if action == "rest":
                body["restUntilMs"] = rest_until_ms
            assert station.revision is not None
            return await self._mutate(path, body, station.revision, _new_key())

        try:
            reply = await send()
        except RadioError as err:
            if err.code != "stale-feedback-revision" and not isinstance(
                err, RadioStaleError
            ):
                raise
            reply = await send()
        return _operation_id(reply.data)

    async def wait_operation(
        self, operation_id: str, timeout: float = 20
    ) -> dict[str, Any] | None:
        """The finished operation, or None if it is still running after `timeout` seconds."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            operation = await self.operation(operation_id)
            if operation.get("status") in (
                "completed",
                "succeeded",
                "failed",
                "cancelled",
            ):
                return operation
            if loop.time() + OPERATION_POLL_SECONDS > deadline:
                return None
            await asyncio.sleep(OPERATION_POLL_SECONDS)

    # ── Live updates ─────────────────────────────────────────────────────

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """The radio's event stream: `{"type": "connected"}` first, then each update.

        Updates carry only their type (`status`, `stations`, `settings`, `libraries`,
        `operation`); a client reads the resource again.
        """
        try:
            async with self._session.get(
                self.address.url("/api/v1/events"),
                headers=self._headers("text/event-stream"),
                ssl=self._pin,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(
                    total=None,
                    sock_connect=REQUEST_TIMEOUT,
                    sock_read=EVENTS_READ_TIMEOUT,
                ),
            ) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise _error(response.status, json.loads(text) if text else None)
                yield {"type": "connected"}
                data: list[str] = []
                async for raw in response.content:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if not line:
                        if data:
                            event = _parse_event("\n".join(data))
                            data = []
                            if event is not None:
                                yield event
                        continue
                    if line.startswith(":"):
                        continue
                    field, _, value = line.partition(":")
                    if field == "data":
                        data.append(value.removeprefix(" "))
        except aiohttp.ServerFingerprintMismatch as err:
            raise RadioIdentityError("identity-changed") from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise RadioConnectionError("unreachable") from err
        except json.JSONDecodeError as err:
            raise RadioError("unexpected-response") from err


def _parse_event(text: str) -> dict[str, Any] | None:
    try:
        event = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        return None
    return event


def _revision(etag: str | None) -> str | None:
    if etag and len(etag) >= 3 and etag.startswith('"') and etag.endswith('"'):
        return etag[1:-1]
    return None


def _operation_id(data: Any) -> str | None:
    if isinstance(data, dict) and isinstance(data.get("operationId"), str):
        return data["operationId"]
    return None


def _error(status: int, payload: Any) -> RadioError:
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    code = code if isinstance(code, str) else f"http-{status}"
    if status == 401:
        return RadioAuthError(code, status)
    if status == 403 and code == "insufficient-scope":
        return RadioScopeError(code, status)
    if status == 421:
        return RadioHostRejected(code, status)
    if status == 412:
        current = error.get("currentRevision") if isinstance(error, dict) else None
        return RadioStaleError(code, current if isinstance(current, str) else None)
    if status >= 500 and code in ("internal-error", "shutting-down", "request-timeout"):
        return RadioConnectionError(code, status)
    return RadioError(code, status)
