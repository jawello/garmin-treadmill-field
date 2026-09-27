"""The single BLE link to the treadmill: find, connect, poll, send belt commands."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

from bumble.core import UUID, AdvertisingData
from bumble.device import Device, Peer
from bumble.hci import Address, OwnAddressType

from .hub import StatusHub
from .protocol import NOTIFY_UUID, QUERY, SERVICE_UUID, START, STOP, WRITE_UUID, parse_status

log = logging.getLogger(__name__)
_UUID_LISTS = (
    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
    AdvertisingData.INCOMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
)


class LinkError(Exception):
    pass


def parse_address(text: str) -> Address:
    if text.endswith("/P"):
        return Address(text[:-2], Address.PUBLIC_DEVICE_ADDRESS)
    return Address(text, Address.RANDOM_DEVICE_ADDRESS)


def format_address(address: Address) -> str:
    raw = address.to_string(with_type_qualifier=False)
    return f"{raw}/P" if address.address_type == Address.PUBLIC_DEVICE_ADDRESS else raw


class TreadmillClient:
    def __init__(
        self,
        device: Device,
        hub: StatusHub,
        address: str | None,
        own_address_type: OwnAddressType,
        on_address: Callable[[str], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        poll_interval: float = 1.0,
        write_gap: float = 0.4,
        stale_after: float = 5.0,
        backoff: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0),
        scan_timeout: float = 10.0,
        connect_timeout: float = 10.0,
        command_ttl: float = 5.0,
    ) -> None:
        self._device = device
        self._hub = hub
        self._address = address
        self._own_address_type = own_address_type
        self._on_address = on_address
        self._clock = clock
        self._poll_interval = poll_interval
        self._write_gap = write_gap
        self._stale_after = stale_after
        self._backoff = backoff
        self._scan_timeout = scan_timeout
        self._connect_timeout = connect_timeout
        self._command_ttl = command_ttl
        self._pending: list[tuple[bytes, float]] = []  # (command, queued at)
        self._attempt = 0

    def send_command(self, command: bytes) -> None:
        now = self._clock()
        if command == STOP:
            self._pending = [(STOP, now)]
        elif command == START:
            self._pending = [(c, t) for c, t in self._pending if c != START] + [(START, now)]
        else:
            raise ValueError(f"not a belt command: {command.hex()}")

    async def run(self) -> None:
        while True:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # every failure ends in a reconnect
                log.warning("treadmill link lost: %s", str(error) or type(error).__name__)
            self._hub.set_link(False)
            delay = self._backoff[min(self._attempt, len(self._backoff) - 1)]
            self._attempt += 1
            await asyncio.sleep(delay)

    async def _session(self) -> None:
        address = await self._resolve_address()
        connection = await self._device.connect(
            address, own_address_type=self._own_address_type, timeout=self._connect_timeout
        )
        lost = asyncio.Event()
        connection.on("disconnection", lambda *_: lost.set())
        log.info("treadmill connected %s", format_address(address))
        try:
            peer = Peer(connection)
            services = await peer.discover_service(UUID(SERVICE_UUID))
            if not services:
                raise LinkError("FE00 service not found")
            chars = {c.uuid: c for c in await peer.discover_characteristics(service=services[0])}
            notify, write = chars.get(UUID(NOTIFY_UUID)), chars.get(UUID(WRITE_UUID))
            if notify is None or write is None:
                raise LinkError("FE01/FE02 not found")
            last_valid = [self._clock()]

            def on_notify(value: bytes) -> None:
                status = parse_status(bytes(value))
                if status is None:
                    return
                last_valid[0] = self._clock()
                self._attempt = 0
                self._hub.set_link(True)
                self._hub.publish(status)

            await peer.subscribe(notify, on_notify)
            while not lost.is_set():
                command = self._next_command()
                await write.write_value(command, with_response=False)
                if command == START:
                    self._hub.note_start()
                if command != QUERY:
                    log.info("sent %s to treadmill", "start" if command == START else "stop")
                if self._clock() - last_valid[0] > self._stale_after:
                    raise LinkError("no valid status")
                await asyncio.sleep(self._write_gap if self._pending else self._poll_interval)
            raise LinkError("disconnected")
        finally:
            if not lost.is_set():
                with contextlib.suppress(Exception):
                    await connection.disconnect()

    def _next_command(self) -> bytes:
        # A belt command that waited longer than command_ttl (link down, reconnecting) is
        # dropped: a late START could start the belt with nobody on it.
        now = self._clock()
        while self._pending:
            command, queued_at = self._pending.pop(0)
            if now - queued_at <= self._command_ttl:
                return command
            log.warning("dropped stale %s command", "start" if command == START else "stop")
        return QUERY

    async def _resolve_address(self) -> Address:
        if self._address:
            return parse_address(self._address)
        found: asyncio.Future[Address] = asyncio.get_running_loop().create_future()
        service = UUID(SERVICE_UUID)

        def on_advertisement(advertisement) -> None:
            for kind in _UUID_LISTS:
                if service in (advertisement.data.get(kind) or []) and not found.done():
                    found.set_result(advertisement.address)

        self._device.on("advertisement", on_advertisement)
        try:
            await self._device.start_scanning(legacy=True, active=True, filter_duplicates=True)
            address = await asyncio.wait_for(found, self._scan_timeout)
        finally:
            self._device.remove_listener("advertisement", on_advertisement)
            with contextlib.suppress(Exception):
                await self._device.stop_scanning()
        self._address = format_address(address)
        log.info("treadmill found at %s", self._address)
        if self._on_address:
            self._on_address(self._address)
        return address
