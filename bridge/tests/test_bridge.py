import asyncio

from bumble.hci import OwnAddressType

from treadmill_bridge.bridge import Bridge
from treadmill_bridge.footpod import FootPod
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.odometer import Odometer
from treadmill_bridge.treadmill import TreadmillClient
from tests.fakes import FakeTreadmill, FakeWatch, virtual_device


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakePeripheral:
    def __init__(self):
        self.advertising = False
        self.calls = []

    async def start(self):
        self.advertising = True
        self.calls.append("start")

    async def stop(self):
        self.advertising = False
        self.calls.append("stop")

    async def tick(self, now):
        self.calls.append("tick")


async def test_advertise_only_with_link_and_grace():
    clock = Clock()
    hub = StatusHub(clock)
    pod, ciq = FakePeripheral(), FakePeripheral()
    bridge = Bridge(hub, pod, ciq, clock=clock, grace_s=30.0)
    await bridge.tick()
    assert not pod.advertising and not ciq.advertising
    hub.set_link(True)
    await bridge.tick()
    assert pod.advertising and ciq.advertising
    clock.t = 100.0
    hub.set_link(False)
    clock.t = 129.0
    await bridge.tick()
    assert pod.advertising
    clock.t = 130.0
    await bridge.tick()
    assert not pod.advertising and not ciq.advertising


async def test_runs_without_ciq():
    hub = StatusHub()
    pod = FakePeripheral()
    bridge = Bridge(hub, pod, None)
    hub.set_link(True)
    await bridge.tick()
    assert pod.advertising


async def test_grace_then_stop_only_watch_links(link):
    tm = FakeTreadmill(virtual_device(link, "treadmill"))
    tm.install()
    await tm.start()
    radio = virtual_device(link, "bridge-a")
    watch_dev = virtual_device(link, "watch")
    await radio.power_on()
    await watch_dev.power_on()
    hub = StatusHub()
    pod = FootPod(radio, hub, Odometer(), OwnAddressType.RANDOM)
    pod.install()
    client = TreadmillClient(
        radio, hub, str(tm.device.random_address), OwnAddressType.RANDOM,
        poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,),
    )
    task = asyncio.create_task(client.run())
    bridge = Bridge(hub, pod, None, grace_s=0.0)
    try:
        for _ in range(100):
            await bridge.tick()
            if hub.link_up and pod.advertising:
                break
            await asyncio.sleep(0.02)
        await FakeWatch(watch_dev).connect(radio.random_address)
        await asyncio.sleep(0.1)
        assert len(radio.connections) == 2  # treadmill (central) + watch (peripheral)
        hub.set_link(False)  # simulate the treadmill link going down in the hub only
        await bridge.tick()
        await asyncio.sleep(0.1)
        roles = [c.role for c in radio.connections.values()]
        assert len(roles) == 1  # watch dropped, treadmill link kept
    finally:
        task.cancel()


class BrokenPeripheral(FakePeripheral):
    async def start(self):
        raise RuntimeError("HCI command disallowed")

    async def stop(self):
        raise RuntimeError("unknown connection identifier")

    async def tick(self, now):
        raise RuntimeError("notify failed")


async def test_one_failing_component_does_not_break_the_tick():
    clock = Clock()
    hub = StatusHub(clock)
    pod, ciq = BrokenPeripheral(), FakePeripheral()
    bridge = Bridge(hub, pod, ciq, clock=clock, grace_s=0.0)
    hub.set_link(True)
    await bridge.tick()  # must not raise
    assert ciq.advertising
    hub.set_link(False)
    await bridge.tick()  # footpod.stop raises: ciq.stop must still run
    assert not ciq.advertising
