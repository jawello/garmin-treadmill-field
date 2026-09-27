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
