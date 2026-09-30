import asyncio
import struct

from bumble.hci import OwnAddressType

from treadmill_bridge import protocol as p
from treadmill_bridge.app import Timings, build, status_snapshot
from treadmill_bridge.config import Config, State
from treadmill_bridge.storage import Store
from tests.fakes import FakeTreadmill, FakeWatch, virtual_device

FAST = Timings(poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,), grace_s=0.3, tick_s=0.05, flush_s=0.2)


async def start_system(link, tmp_path, with_b=True, hold=False, stop_belt=False, timings=FAST):
    tm = FakeTreadmill(virtual_device(link, "treadmill"))
    tm.install()
    tm.running = not stop_belt
    await tm.start()
    dev_a = virtual_device(link, "radio-a")
    dev_b = virtual_device(link, "radio-b") if with_b else None
    config = Config(api_token="t", treadmill_address=str(tm.device.random_address), hold_speed_during_start=hold)
    components = build(
        dev_a, dev_b, config, Store(str(tmp_path / "e.db")), State(str(tmp_path / "s.json")),
        OwnAddressType.RANDOM, time_synced=lambda: True, timings=timings,
    )
    await dev_a.power_on()
    if dev_b:
        await dev_b.power_on()
    task = asyncio.create_task(components.run_ble())
    for _ in range(150):
        if components.hub.link_up and components.footpod.advertising:
            break
        await asyncio.sleep(0.02)
    return tm, components, task


async def test_end_to_end_footpod_field_and_belt(link, tmp_path):
    tm, c, task = await start_system(link, tmp_path)
    try:
        watch_dev = virtual_device(link, "watch")
        await watch_dev.power_on()
        watch = FakeWatch(watch_dev)
        pod_conn = await watch.connect(c.dev_a.random_address)
        await pod_conn.pair()
        rsc = await watch.subscribe(pod_conn, "1814", "2A53")
        _, speed, _, _ = struct.unpack("<BHBI", await asyncio.wait_for(rsc.get(), 2))
        assert speed == 320
        field_conn = await watch.connect(c.dev_b.random_address)
        fe01 = await watch.subscribe(field_conn, p.SERVICE_UUID, p.NOTIFY_UUID)
        await watch.write(field_conn, p.SERVICE_UUID, p.WRITE_UUID, p.QUERY)
        assert p.parse_status(await asyncio.wait_for(fe01.get(), 2)) is not None
        await watch.write(field_conn, p.SERVICE_UUID, p.WRITE_UUID, p.STOP)
        for _ in range(100):
            if p.STOP in tm.writes:
                break
            await asyncio.sleep(0.02)
        assert p.STOP in tm.writes
        await asyncio.sleep(0.4)
        snapshot = status_snapshot(c)
        assert snapshot["treadmill"]["link_up"] and snapshot["field_bridge"]["present"]
        assert any(b["steps"] > 0 for b in c.store.buckets(0, 10**10))
    finally:
        task.cancel()


async def test_runs_without_radio_b(link, tmp_path):
    _, c, task = await start_system(link, tmp_path, with_b=False)
    try:
        assert c.hub.link_up and c.footpod.advertising and c.ciq is None
        assert status_snapshot(c)["field_bridge"] == {"present": False, "advertising": False}
    finally:
        task.cancel()


async def test_storage_failure_does_not_stop_the_daemon(link, tmp_path):
    _, c, task = await start_system(link, tmp_path, with_b=False)
    try:
        def broken_flush(_now):
            raise OSError("disk I/O error")

        c.recorder.flush = broken_flush
        await asyncio.sleep(0.6)  # several flush intervals (FAST.flush_s = 0.2)
        assert not task.done()
        assert c.hub.link_up and c.footpod.advertising
    finally:
        task.cancel()


async def test_steps_not_recorded_without_the_owners_watch(link, tmp_path):
    # Someone else walks: the treadmill counts steps, but no bonded watch is connected.
    _, c, task = await start_system(link, tmp_path)
    try:
        await asyncio.sleep(0.8)
        c.recorder.flush(10**10)
        assert c.store.buckets(0, 10**11) == []
        assert status_snapshot(c)["owner"]["present"] is False
    finally:
        task.cancel()


async def test_unbonded_watch_does_not_count(link, tmp_path):
    _, c, task = await start_system(link, tmp_path)
    try:
        watch_dev = virtual_device(link, "not-owner")
        await watch_dev.power_on()
        await FakeWatch(watch_dev).connect(c.dev_a.random_address)  # connected but never paired
        await asyncio.sleep(0.8)
        c.recorder.flush(10**10)
        assert c.store.buckets(0, 10**11) == []
    finally:
        task.cancel()


async def test_build_leaves_the_keystore_to_power_on(link, tmp_path):
    # Bumble creates the persistent JsonKeyStore (keys.json) in power_on(); build() runs
    # earlier and must not replace it, or bonds would neither load nor persist.
    dev_a = virtual_device(link, "radio-a")
    dev_a.keystore = None  # as in production before power_on()
    build(dev_a, None, Config(api_token="t"), Store(str(tmp_path / "k.db")), State(str(tmp_path / "k.json")),
          OwnAddressType.RANDOM, time_synced=lambda: True, timings=FAST)
    assert dev_a.keystore is None


async def test_start_request_pushes_hold_speed_to_the_watch_at_once(link, tmp_path):
    slow_ticks = Timings(poll_interval=0.05, write_gap=0.02, stale_after=0.5, backoff=(0.05,), grace_s=0.3, tick_s=1.0, flush_s=0.2)
    tm, c, task = await start_system(link, tmp_path, hold=True, stop_belt=True, timings=slow_ticks)
    try:
        watch_dev = virtual_device(link, "watch")
        await watch_dev.power_on()
        watch = FakeWatch(watch_dev)
        pod = await watch.connect(c.dev_a.random_address)
        await pod.pair()
        rsc = await watch.subscribe(pod, "1814", "2A53")
        field = await watch.connect(c.dev_b.random_address)
        await asyncio.sleep(0.3)
        while not rsc.empty():
            rsc.get_nowait()
        await watch.write(field, p.SERVICE_UUID, p.WRITE_UUID, p.START)
        data = await asyncio.wait_for(rsc.get(), 0.15)  # well before the next 1 s tick
        _, speed, _, _ = struct.unpack("<BHBI", data)
        assert speed == round(1.0 / 3.6 * 256)
    finally:
        task.cancel()
