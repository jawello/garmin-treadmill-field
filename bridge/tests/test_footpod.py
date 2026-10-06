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
    assert pod_speed_mps(stopped, 21.0, 5.0, hold=True) == 0.0  # 16 s after start
    assert pod_speed_mps(None, 10.0, 9.0, hold=True) == 0.0  # no data at all



def test_pod_speed_holds_through_the_slow_ramp_after_start():
    ramp = p.parse_status(p.build_status(1, 4, 0, 0, 0))  # 0.4 km/h right after the countdown
    hold = 1.0 / 3.6
    assert abs(pod_speed_mps(ramp, 10.0, 5.0, hold=True) - hold) < 1e-9  # 5 s after start
    assert abs(pod_speed_mps(ramp, 19.0, 5.0, hold=True) - hold) < 1e-9  # 14 s after start
    assert pod_speed_mps(ramp, 21.0, 5.0, hold=True) == 4 / 36  # 16 s: the real speed
    assert pod_speed_mps(ramp, 10.0, 5.0, hold=False) == 4 / 36
    assert pod_speed_mps(ramp, 10.0, None, hold=True) == 4 / 36  # slow walk, no start asked
    walking = p.parse_status(p.build_status(1, 45, 0, 0, 0))
    assert pod_speed_mps(walking, 10.0, 5.0, hold=True) == 1.25  # never lowered

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


async def _adverts_seen(link, address, seconds=0.6) -> int:
    scanner = virtual_device(link, "scanner")
    await scanner.power_on()
    seen = []
    scanner.on("advertisement", lambda adv: seen.append(adv) if adv.address == address else None)
    await scanner.start_scanning(legacy=True)
    await asyncio.sleep(seconds)
    await scanner.stop_scanning()
    return len(seen)


async def test_stop_with_watch_connected_stays_off_air_on_legacy_controller(link, monkeypatch):
    # The Pi 3B+ built-in controller has no extended advertising: force Bumble's legacy path.
    from bumble.device import Device

    monkeypatch.setattr(Device, "supports_le_extended_advertising", property(lambda self: False))
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    pod = FootPod(pod_dev, StatusHub(), Odometer(), OwnAddressType.RANDOM)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    await pod.start()
    await FakeWatch(watch_dev).connect(pod_dev.random_address)
    await asyncio.sleep(0.1)
    await pod.stop()
    await asyncio.sleep(0.2)
    assert not pod_dev.is_advertising
    assert await _adverts_seen(link, pod_dev.random_address) == 0


async def test_start_readvertises_after_watch_leaves(link, monkeypatch):
    from bumble.device import Device

    monkeypatch.setattr(Device, "supports_le_extended_advertising", property(lambda self: False))
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    pod = FootPod(pod_dev, StatusHub(), Odometer(), OwnAddressType.RANDOM)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    await pod.start()
    conn = await FakeWatch(watch_dev).connect(pod_dev.random_address)
    await asyncio.sleep(0.1)
    await pod.start()  # a tick while the watch is connected: no advertising
    assert not pod_dev.is_advertising
    await conn.disconnect()
    await asyncio.sleep(0.1)
    await pod.start()  # next tick after the watch left: back on air
    assert pod_dev.is_advertising


async def test_payload_logs_when_speed_drops_to_zero(link, caplog):
    now = [100.0]
    hub, odo = StatusHub(clock=lambda: now[0]), Odometer()
    pod = FootPod(virtual_device(link, "pod"), hub, odo, OwnAddressType.RANDOM, clock=lambda: now[0])
    hub.publish(p.parse_status(p.build_status(1, 45, 0, 0, 0)))
    pod.payload(now[0])
    now[0] = 104.5  # no reply from the treadmill for 4.5 s
    with caplog.at_level("WARNING", logger="treadmill_bridge.footpod"):
        pod.payload(now[0])
        pod.payload(now[0])  # still zero: reported once
    drops = [r.getMessage() for r in caplog.records if "speed 0" in r.getMessage()]
    assert drops == ["foot pod speed 0 after 1.25 m/s: no fresh status (last 4.5 s ago)"]


async def _subscribed_pod(link, backlog):
    pod_dev, watch_dev = virtual_device(link, "pod"), virtual_device(link, "watch")
    hub, odo = StatusHub(), Odometer()
    pod = FootPod(pod_dev, hub, odo, OwnAddressType.RANDOM, backlog=backlog)
    pod.install()
    await pod_dev.power_on()
    await watch_dev.power_on()
    hub.publish(p.parse_status(p.build_status(1, 45, 0, 0, 0)))
    await pod.start()
    watch = FakeWatch(watch_dev)
    conn = await watch.connect(pod_dev.random_address)
    await conn.pair()
    return pod, await watch.subscribe(conn, "1814", "2A53")


async def test_skips_a_measurement_while_the_watch_has_three_waiting(link):
    # The watch still has older ones to take; queueing more only grows its backlog.
    pod, rsc = await _subscribed_pod(link, backlog=lambda _connection: 3)
    await pod.tick(0.0)
    await asyncio.sleep(0.2)
    assert rsc.empty()


async def test_sends_while_the_watch_keeps_up(link):
    pod, rsc = await _subscribed_pod(link, backlog=lambda _connection: 2)
    await pod.tick(0.0)
    assert await asyncio.wait_for(rsc.get(), 2)


async def test_link_backlog_counts_packets_not_yet_confirmed(link):
    from treadmill_bridge.ble import link_backlog

    pod, rsc = await _subscribed_pod(link, backlog=None)
    connection = next(iter(pod._device.connections.values()))
    assert link_backlog(connection) == 0
