import asyncio

from bumble.hci import OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.ciq_link import CiqLink
from treadmill_bridge.hub import StatusHub
from tests import fixtures as f
from tests.fakes import FakeWatch, virtual_device


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def setup(link):
    clock = Clock()
    hub = StatusHub(clock)
    commands = []
    radio, watch_dev = virtual_device(link, "bridge-b"), virtual_device(link, "watch")
    ciq = CiqLink(radio, hub, commands.append, OwnAddressType.RANDOM, clock=clock)
    ciq.install()
    await radio.power_on()
    await watch_dev.power_on()
    await ciq.start()
    watch = FakeWatch(watch_dev)
    conn = await watch.connect(radio.random_address)
    queue = await watch.subscribe(conn, p.SERVICE_UUID, p.NOTIFY_UUID)
    return clock, hub, commands, watch, conn, queue, ciq


async def test_query_answered_with_cached_raw_packet(link):
    clock, hub, _, watch, conn, queue, _ = await setup(link)
    hub.publish(p.parse_status(f.WALKING))
    clock.t = 2.9
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.QUERY)
    assert await asyncio.wait_for(queue.get(), 2) == f.WALKING


async def test_stale_cache_gets_no_answer(link):
    clock, hub, _, watch, conn, queue, _ = await setup(link)
    hub.publish(p.parse_status(f.WALKING))
    clock.t = 3.5
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.QUERY)
    await asyncio.sleep(0.2)
    assert queue.empty()


async def test_commands_forwarded_and_unknown_dropped(link):
    _, _, commands, watch, conn, _, _ = await setup(link)
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.START)
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, bytes.fromhex("f7a20102a5fd"))  # set speed: not allowed
    await watch.write(conn, p.SERVICE_UUID, p.WRITE_UUID, p.STOP)
    await asyncio.sleep(0.2)
    assert commands == [p.START, p.STOP]


async def test_stop_disconnects_watch(link):
    _, _, _, _, _, _, ciq = await setup(link)
    await ciq.stop()
    await asyncio.sleep(0.1)
    assert not ciq.advertising and not ciq._device.connections


async def test_stop_with_watch_connected_stays_off_air_on_legacy_controller(link, monkeypatch):
    from bumble.device import Device

    monkeypatch.setattr(Device, "supports_le_extended_advertising", property(lambda self: False))
    from tests.test_footpod import _adverts_seen

    _, _, _, _, _, _, ciq = await setup(link)
    await ciq.stop()
    await asyncio.sleep(0.2)
    assert not ciq._device.connections
    assert await _adverts_seen(link, ciq._device.random_address) == 0
