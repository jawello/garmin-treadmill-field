"""Virtual BLE participants for tests (Bumble LocalLink)."""

from __future__ import annotations

import asyncio
import itertools

from bumble.controller import Controller
from bumble.core import UUID
from bumble.device import Device, Peer
from bumble.hci import Address, OwnAddressType
from bumble.host import Host
from bumble.link import LocalLink
from bumble.transport.common import AsyncPipeSink

_counter = itertools.count(1)


def virtual_device(link: LocalLink, name: str) -> Device:
    n = next(_counter)
    public = f"F0:00:00:00:00:{n:02X}"
    controller = Controller(name, link=link, public_address=public)
    return Device(name=name, address=Address(f"C0:00:00:00:00:{n:02X}"), host=Host(controller, AsyncPipeSink(controller)))


class FakeWatch:
    """A central that connects to a peripheral, subscribes and collects notifications."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self.connections = {}

    async def connect(self, address: Address):
        return await self.device.connect(address, own_address_type=OwnAddressType.RANDOM, timeout=5)

    async def subscribe(self, connection, service_uuid: str, char_uuid: str) -> asyncio.Queue:
        peer = Peer(connection)
        service = (await peer.discover_service(UUID(service_uuid)))[0]
        chars = await peer.discover_characteristics(service=service)
        target = next(c for c in chars if c.uuid == UUID(char_uuid))
        queue: asyncio.Queue = asyncio.Queue()
        await peer.subscribe(target, lambda value: queue.put_nowait(bytes(value)))
        return queue

    async def write(self, connection, service_uuid: str, char_uuid: str, value: bytes) -> None:
        peer = Peer(connection)
        service = (await peer.discover_service(UUID(service_uuid)))[0]
        chars = await peer.discover_characteristics(service=service)
        target = next(c for c in chars if c.uuid == UUID(char_uuid))
        await target.write_value(value, with_response=False)


import struct

from bumble.core import AdvertisingData
from bumble.gatt import Characteristic, CharacteristicValue, Service

from treadmill_bridge import protocol as p


# The R1 Pro declares its service and characteristics with 16-bit UUIDs; a GATT
# "find by type value" only matches the same wire form, so the fake must too.
TREADMILL_SERVICE, TREADMILL_NOTIFY, TREADMILL_WRITE = "FE00", "FE01", "FE02"


class FakeTreadmill:
    """FE00 server that behaves like the R1 Pro: answers queries, obeys start/stop."""

    def __init__(self, device: Device) -> None:
        self.device = device
        self.writes: list[bytes] = []
        self.running = True
        self.steps = 0
        self.notify = Characteristic(
            TREADMILL_NOTIFY,
            Characteristic.Properties.READ | Characteristic.Properties.NOTIFY,
            Characteristic.READABLE,
            bytes(20),
        )
        self.write = Characteristic(
            TREADMILL_WRITE,
            Characteristic.Properties.WRITE_WITHOUT_RESPONSE | Characteristic.Properties.WRITE,
            Characteristic.WRITEABLE,
            CharacteristicValue(write=self._on_write),
        )

    def install(self) -> None:
        self.device.add_service(Service(TREADMILL_SERVICE, [self.notify, self.write]))

    async def start(self) -> None:
        await self.device.power_on()
        await self.device.start_advertising(
            own_address_type=OwnAddressType.RANDOM,
            advertising_data=bytes(
                AdvertisingData(
                    [(AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS, struct.pack("<H", 0xFE00))]
                )
            ),
            auto_restart=True,
        )

    async def drop(self) -> None:
        for connection in list(self.device.connections.values()):
            await connection.disconnect()

    def _on_write(self, connection, value) -> None:
        data = bytes(value)
        self.writes.append(data)
        if data == p.START:
            self.running = True
        elif data == p.STOP:
            self.running = False
        if self.running:
            self.steps += 2
        packet = p.build_status(1 if self.running else 0, 45 if self.running else 0, 0, self.steps // 10, self.steps)
        asyncio.ensure_future(self.device.notify_subscriber(connection, self.notify, packet))
