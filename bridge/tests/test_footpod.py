import asyncio
import struct

from bumble.hci import OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.footpod import FootPod, pod_speed_mps, rsc_measurement
from treadmill_bridge.hub import StatusHub
from treadmill_bridge.odometer import Odometer
from tests.fakes import FakeWatch, virtual_device


def test_rsc_measurement_bytes():
    # 4.5 km/h, 105 steps/min -> 52 strides/min, 123.4 m
    assert rsc_measurement(1.25, 52, 123.4) == struct.pack("<BHBI", 0x02, 320, 52, 1234)
    assert rsc_measurement(-1, -5, -3) == struct.pack("<BHBI", 0x02, 0, 0, 0)
    assert rsc_measurement(1000, 999, 1e9) == struct.pack("<BHBI", 0x02, 0xFFFF, 0xFF, 0xFFFFFFFF)


def test_pod_speed_hold_during_start():
    run = p.parse_status(p.build_status(1, 45, 0, 0, 0))
    countdown = p.parse_status(p.build_status(8, 0, 0, 0, 0))
    stopped = p.parse_status(p.build_status(0, 0, 0, 0, 0))
    assert pod_speed_mps(run, 10.0, None, hold=True) == 1.25
    assert pod_speed_mps(countdown, 10.0, None, hold=False) == 0.0
    assert abs(pod_speed_mps(countdown, 10.0, None, hold=True) - 1.0 / 3.6) < 1e-9
    assert abs(pod_speed_mps(stopped, 10.0, 5.0, hold=True) - 1.0 / 3.6) < 1e-9  # 5 s after start
    assert pod_speed_mps(stopped, 20.0, 5.0, hold=True) == 0.0  # 15 s after start
    assert pod_speed_mps(None, 10.0, 9.0, hold=True) == 0.0  # no data at all


async def test_watch_pairs_and_receives_measurement(link):
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    hub, odo = StatusHub(), Odometer()
    pod = FootPod(pod_dev, hub, odo, OwnAddressType.RANDOM)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    status = p.parse_status(p.build_status(1, 45, 0, 0, 0))
    hub.publish(status)
    odo.update(status, 0.0)
    await pod.start()
    assert pod.advertising
    watch = FakeWatch(watch_dev)
    conn = await watch.connect(pod_dev.random_address)
    await conn.pair()
    assert conn.is_encrypted
    queue = await watch.subscribe(conn, "1814", "2A53")
    await pod.tick(0.0)
    data = await asyncio.wait_for(queue.get(), 2)
    flags, speed, cadence, dist = struct.unpack("<BHBI", data)
    assert (flags, speed, cadence) == (0x02, 320, 0)


async def test_stop_disconnects_watch_and_stops_advertising(link):
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    pod = FootPod(pod_dev, StatusHub(), Odometer(), OwnAddressType.RANDOM)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    await pod.start()
    await FakeWatch(watch_dev).connect(pod_dev.random_address)
    await asyncio.sleep(0.1)
    await pod.stop()
    await asyncio.sleep(0.1)
    assert not pod.advertising and not pod_dev.connections
